import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../api/dio_client.dart' show kBaseUrl;

/// 手机推送(自建通道):前台服务里保持一条 WebSocket 长连接到 backend /push/ws,
/// 收到 notify / 定时任务完成即弹系统通知。国内无 GMS 收不到 FCM、厂商通道要企业资质,
/// 自建长连是个人开发者唯一全自控路径;代价是通知栏常驻一条低优先级「在线」通知 +
/// 用户需一次性允许自启动/后台运行(ColorOS 引导见设置页)。
///
/// 鉴权:refresh token 走 WS subprotocol(["refresh", <token>]),服务端只验证不消耗
/// (30 天有效)。refresh 过期(用户 30 天没开 app)→ 1008 拒 → 通道静默,开 app 重新
/// 登录即恢复。

const _channelId = 'agent_cloud_push';
const kPushEnabledKey = 'push.enabled'; // secure_storage 开关(设置页读写)

final _notifications = FlutterLocalNotificationsPlugin();

/// 主 isolate 调用:初始化本地通知(含点击回调注册)。冷启动点通知的 payload 由
/// main 里 getNotificationAppLaunchDetails 消费。
Future<void> initLocalNotifications(
    void Function(String? payload) onTap) async {
  const android = AndroidInitializationSettings('@mipmap/ic_launcher');
  await _notifications.initialize(
    settings: const InitializationSettings(android: android),
    onDidReceiveNotificationResponse: (resp) => onTap(resp.payload),
  );
}

/// 冷启动:app 是被「点通知」拉起的话,返回该通知的 session_id(否则 null)。
Future<String?> launchNotificationSession() async {
  final details = await _notifications.getNotificationAppLaunchDetails();
  final payload = details?.notificationResponse?.payload;
  return (details?.didNotificationLaunchApp ?? false) &&
          payload != null &&
          payload.isNotEmpty
      ? payload
      : null;
}

/// Android 13+ 通知运行时权限(设置页开启开关时调)。
Future<bool> requestNotificationPermission() async {
  final impl = _notifications.resolvePlatformSpecificImplementation<
      AndroidFlutterLocalNotificationsPlugin>();
  return await impl?.requestNotificationsPermission() ?? false;
}

/// 前台服务配置(幂等)。
void initForegroundTask() {
  FlutterForegroundTask.init(
    androidNotificationOptions: AndroidNotificationOptions(
      channelId: 'agent_cloud_keepalive',
      channelName: '后台连接',
      channelDescription: '保持与助手的推送连接',
      channelImportance: NotificationChannelImportance.MIN, // 常驻通知尽量安静
      priority: NotificationPriority.MIN,
    ),
    iosNotificationOptions: const IOSNotificationOptions(),
    foregroundTaskOptions: ForegroundTaskOptions(
      eventAction: ForegroundTaskEventAction.repeat(240000), // 4min 心跳(NAT 保活)
      autoRunOnBoot: true, // 重启后随系统拉起(仍受 ROM 自启动白名单约束)
      allowWakeLock: true,
    ),
  );
}

Future<void> startPushService() async {
  initForegroundTask();
  if (await FlutterForegroundTask.isRunningService) return;
  await FlutterForegroundTask.startService(
    serviceTypes: [ForegroundServiceTypes.specialUse], // dataSync 在 targetSdk 35+ 有 6h 时限
    serviceId: 301,
    notificationTitle: 'Agent Cloud 在线',
    notificationText: '推送通道已连接',
    callback: pushServiceCallback,
  );
}

Future<void> stopPushService() => FlutterForegroundTask.stopService();

@pragma('vm:entry-point')
void pushServiceCallback() {
  FlutterForegroundTask.setTaskHandler(_PushTaskHandler());
}

class _PushTaskHandler extends TaskHandler {
  WebSocket? _ws;
  bool _connecting = false;

  @override
  Future<void> onStart(DateTime timestamp, TaskStarter starter) async {
    await _ensureNotificationsInit();
    unawaited(_connect());
  }

  @override
  void onRepeatEvent(DateTime timestamp) {
    // 4min 周期:活连接发应用层心跳;断了就重连(Doze 下 repeat 由 alarm 驱动,可靠)。
    final ws = _ws;
    if (ws != null && ws.readyState == WebSocket.open) {
      ws.add(jsonEncode({'type': 'ping'}));
    } else if (!_connecting) {
      unawaited(_connect());
    }
  }

  @override
  Future<void> onDestroy(DateTime timestamp, bool isTimeout) async {
    await _ws?.close();
  }

  Future<void> _ensureNotificationsInit() async {
    // FGS isolate 独立初始化插件实例(点击回调走主 isolate 的注册,这里只管 show)。
    const android = AndroidInitializationSettings('@mipmap/ic_launcher');
    await _notifications.initialize(
        settings: const InitializationSettings(android: android));
  }

  Future<void> _connect() async {
    _connecting = true;
    try {
      // 用 refresh token 鉴权(30 天):FGS 拿不到新 access(15min,主 app 不在前台不刷新),
      // 且 refresh 严格轮换 + 双花全吊销,FGS 绝不能自己换发 —— 服务端对 WS 只验证不消耗。
      // 主 app 活跃时轮换的新 refresh 落回 secure_storage,这里每次重连重读即自动跟上。
      final token =
          await const FlutterSecureStorage().read(key: 'refresh_token');
      if (token == null || token.isEmpty) return; // 未登录:下个周期再试
      final wsUrl =
          '${kBaseUrl.replaceFirst('http', 'ws')}/push/ws'; // https→wss, http→ws
      final ws = await WebSocket.connect(wsUrl, protocols: ['refresh', token])
          .timeout(const Duration(seconds: 15)); // 防黑洞连接把 _connecting 闩死
      _ws = ws;
      ws.listen(
        (data) {
          try {
            final m = jsonDecode(data as String) as Map<String, dynamic>;
            if (m['type'] == 'notify' || m['type'] == 'scheduled_done') {
              _show(m);
            }
          } catch (_) {
            // 坏消息忽略,连接保持
          }
        },
        onDone: () => _ws = null,
        onError: (_) => _ws = null,
        cancelOnError: true,
      );
    } catch (_) {
      _ws = null; // 连不上(离线/token 过期):下个 4min 周期再试
    } finally {
      _connecting = false;
    }
  }

  Future<void> _show(Map<String, dynamic> m) async {
    final title = m['title'] as String? ?? '新消息';
    final body = m['body'] as String? ?? '';
    final sid = m['session_id'] as String?;
    await _notifications.show(
      id: DateTime.now().millisecondsSinceEpoch ~/ 1000, // 秒级 id:多条不互相覆盖
      title: title,
      body: body,
      notificationDetails: const NotificationDetails(
        android: AndroidNotificationDetails(
          _channelId,
          '助手通知',
          channelDescription: 'AI 主动提醒与定时任务结果',
          importance: Importance.high,
          priority: Priority.high,
        ),
      ),
      payload: sid, // 点击直达对应会话(主 isolate onTap 消费)
    );
  }
}
