import 'package:flutter/material.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'core/push/push_service.dart';
import 'core/router/app_router.dart';
import 'core/theme/app_theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  FlutterForegroundTask.initCommunicationPort(); // FGS 插件通信口(必须在 runApp 前)
  // 通知点击 → 直达对应会话(运行中直接跳;冷启动延迟等 bootstrap/router 就绪)
  await initLocalNotifications((sid) {
    if (sid != null && sid.isNotEmpty) appRouter?.push('/chat/$sid');
  });
  runApp(const ProviderScope(child: App()));
  // 开关开着就拉起推送前台服务(app 每次打开都确保在跑;停留由服务自己维持)
  final enabled =
      await const FlutterSecureStorage().read(key: kPushEnabledKey) == 'true';
  if (enabled) await startPushService();
  // 冷启动:点通知拉起 app 的场景,等首帧+登录 bootstrap 后再跳会话
  final launch = await launchNotificationSession();
  if (launch != null) {
    Future.delayed(const Duration(milliseconds: 1600), () {
      appRouter?.push('/chat/$launch');
    });
  }
}

class App extends ConsumerWidget {
  const App({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) => MaterialApp.router(
        title: 'Agent Cloud',
        theme: AppTheme.light(),
        routerConfig: ref.watch(routerProvider),
      );
}
