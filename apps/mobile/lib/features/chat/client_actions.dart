import 'package:android_intent_plus/android_intent.dart';

/// 客户端动作工具的 App 端执行(worker 只合成确认,真正的设备操作在此)。
/// chat_controller 收到 set_alarm / add_calendar_event / start_navigation 的 tool_call 后调本函数
/// → 系统 Intent。闹钟走 AlarmClock.ACTION_SET_ALARM,日历走 CalendarContract 的 ACTION_INSERT,
/// 导航唤起高德/百度地图 App(按目的地名搜索导航、无需坐标)—— 都跳系统/地图应用预填,用户确认即可。
const kClientActionTools = {'set_alarm', 'add_calendar_event', 'start_navigation'};

Future<void> handleClientToolCall(String tool, Map<String, dynamic> args) async {
  try {
    switch (tool) {
      case 'set_alarm':
        await _setAlarm(args);
      case 'add_calendar_event':
        await _addCalendar(args);
      case 'start_navigation':
        await _startNavigation(args);
    }
  } catch (_) {
    // 设备动作失败不影响对话(worker 已回合成确认);用户没看到系统界面会再开口
  }
}

Future<void> _setAlarm(Map<String, dynamic> args) async {
  final hour = (args['hour'] as num?)?.toInt();
  final minute = (args['minute'] as num?)?.toInt();
  if (hour == null || minute == null) return;
  final label = args['label'];
  final intent = AndroidIntent(
    action: 'android.intent.action.SET_ALARM', // AlarmClock.ACTION_SET_ALARM
    arguments: <String, dynamic>{
      'android.intent.extra.alarm.HOUR': hour,
      'android.intent.extra.alarm.MINUTES': minute,
      if (label is String && label.trim().isNotEmpty)
        'android.intent.extra.alarm.MESSAGE': label,
      // 不 SKIP_UI:跳系统闹钟界面让用户确认(更透明,且避免某些 ROM 静默设置无反馈)
      'android.intent.extra.alarm.SKIP_UI': false,
    },
  );
  await intent.launch();
}

Future<void> _addCalendar(Map<String, dynamic> args) async {
  final title = args['title'];
  final startStr = args['start'];
  if (title is! String || title.trim().isEmpty || startStr is! String) return;
  final start = DateTime.tryParse(startStr);
  if (start == null) return;
  final endStr = args['end'];
  final end = (endStr is String) ? DateTime.tryParse(endStr) : null;
  final location = args['location'];
  final description = args['description'];
  final intent = AndroidIntent(
    action: 'android.intent.action.INSERT', // CalendarContract ACTION_INSERT
    data: 'content://com.android.calendar/events',
    arguments: <String, dynamic>{
      'title': title,
      'beginTime': start.millisecondsSinceEpoch,
      'endTime':
          (end ?? start.add(const Duration(hours: 1))).millisecondsSinceEpoch,
      if (location is String && location.isNotEmpty) 'eventLocation': location,
      if (description is String && description.isNotEmpty)
        'description': description,
    },
  );
  await intent.launch();
}

/// 导航:按「目的地名称」唤起地图 App 直接进导航(无需坐标,地图自己搜)。探测顺序见
/// [navCandidates] —— 第一个已安装的地图直连;都没装则退到通用 geo:,系统弹地图选择器兜底。
Future<void> _startNavigation(Map<String, dynamic> args) async {
  final dest = args['destination'];
  if (dest is! String || dest.trim().isEmpty) return;
  final mode = (args['mode'] is String) ? args['mode'] as String : 'driving';
  final candidates = navCandidates(dest, mode);
  for (var i = 0; i < candidates.length; i++) {
    final c = candidates[i];
    final intent = AndroidIntent(
      action: 'android.intent.action.VIEW',
      data: c.data,
      package: c.package,
    );
    final isLast = i == candidates.length - 1;
    // 最后一项是 geo 兜底(无 package):直接发让系统弹地图选择器;前面的探测装了才发
    // (canResolveActivity 依赖 AndroidManifest 的 <queries> 声明对应包名/scheme)。
    if (isLast || (await intent.canResolveActivity() ?? false)) {
      await intent.launch();
      return;
    }
  }
}

/// 把目的地 + 出行方式构造成地图唤起候选(高德 → 百度 → 通用 geo: 兜底)。纯函数,便于单测。
/// 驾车时高德优先(keywordNavi 导航体验好);非驾车优先百度(direction 按名称支持步行/公交/骑行,
/// 高德 keywordNavi 仅驾车,故非驾车把它排在百度之后作降级)。
List<({String data, String? package})> navCandidates(String dest, String mode) {
  final d = Uri.encodeComponent(dest.trim());
  final amap = (
    data: 'androidamap://keywordNavi?sourceApplication=SophClaw&keyword=$d&style=2',
    package: 'com.autonavi.minimap',
  );
  final baidu = (
    data: 'baidumap://map/direction?destination=$d&mode=${_baiduMode(mode)}&src=andr.sophclaw.app',
    package: 'com.baidu.BaiduMap',
  );
  final geo = (data: 'geo:0,0?q=$d', package: null);
  return (mode == 'walking' || mode == 'transit' || mode == 'riding')
      ? [baidu, amap, geo]
      : [amap, baidu, geo];
}

String _baiduMode(String mode) {
  const ok = {'driving', 'walking', 'transit', 'riding'};
  return ok.contains(mode) ? mode : 'driving';
}
