import 'package:go_router/go_router.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../widgets/splash_page.dart';
import '../../features/auth/auth_controller.dart';
import '../../features/auth/login_page.dart';
import '../../features/sessions/home_page.dart';
import '../../features/settings/settings_page.dart';
import '../../features/settings/credentials_page.dart';
import '../../features/settings/memory_page.dart';
import '../../features/settings/skills_page.dart';
import '../../features/agent/tools_page.dart';
import '../../features/agent/skills_toggle_page.dart';
import '../../features/agent/agent_settings_page.dart';
import '../../features/agent/agent_memory_page.dart';
import '../../features/files/files_browser_page.dart';
import '../../features/terminal/terminal_page.dart';
import '../../features/chat/chat_page.dart';

/// 路由守卫(纯函数,便于单测)。
/// 关键:bootstrap(isLoading)期间去 /splash —— **绝不能停在 /home**,否则 home 会在
/// 登录前就 build 并发出无 token 的 GET /sessions → 401(新装首登 401 的真因)。
String? authRedirect({
  required bool isLoading,
  required bool loggedIn,
  required String location,
}) {
  if (isLoading) return location == '/splash' ? null : '/splash';
  if (loggedIn) {
    return (location == '/splash' || location == '/login') ? '/home' : null;
  }
  return location == '/login' ? null : '/login';
}

/// router 作为 provider 缓存(稳定);监听登录态变化 → refresh 重新 redirect。
final routerProvider = Provider<GoRouter>((ref) {
  final refresh = ValueNotifier(0);
  ref.listen(authControllerProvider, (_, _) => refresh.value++);
  ref.onDispose(refresh.dispose);
  return GoRouter(
    refreshListenable: refresh,
    initialLocation: '/splash',
    redirect: (ctx, state) {
      final auth = ref.read(authControllerProvider);
      return authRedirect(
        isLoading: auth.isLoading,
        loggedIn: auth.asData?.value != null,
        location: state.matchedLocation,
      );
    },
    routes: [
      GoRoute(path: '/splash', builder: (_, _) => const SplashPage()),
      GoRoute(path: '/login', builder: (_, _) => const LoginPage()),
      GoRoute(path: '/home', builder: (_, _) => const HomePage()),
      GoRoute(
        path: '/chat/:sid',
        // extra:fork 后跳转携带的输入框回填文本(被分叉的那条提问)。
        builder: (_, st) => ChatPage(st.pathParameters['sid']!,
            prefill: st.extra is String ? st.extra as String : null),
      ),
      GoRoute(path: '/settings', builder: (_, _) => const SettingsPage()),
      GoRoute(
          path: '/settings/credentials',
          builder: (_, _) => const CredentialsPage()),
      GoRoute(
          path: '/settings/memory', builder: (_, _) => const MemoryPage()),
      GoRoute(
          path: '/settings/skills', builder: (_, _) => const SkillsPage()),
      GoRoute(
          path: '/agent/:aid/tools',
          builder: (_, st) => ToolsPage(st.pathParameters['aid']!)),
      GoRoute(
          path: '/agent/:aid/skills',
          builder: (_, st) => SkillsTogglePage(st.pathParameters['aid']!)),
      GoRoute(
          path: '/agent/:aid/settings',
          builder: (_, st) => AgentSettingsPage(st.pathParameters['aid']!)),
      GoRoute(
          path: '/agent/:aid/memory',
          builder: (_, st) => AgentMemoryPage(st.pathParameters['aid']!)),
      GoRoute(
          path: '/files',
          // dir/preview:从聊天正文点工作区路径进来的定位(目录 / 待预览文件)。
          builder: (_, st) => FilesPage(
              initialDir: st.uri.queryParameters['dir'] ?? '',
              previewPath: st.uri.queryParameters['preview'])),
      GoRoute(path: '/terminal', builder: (_, _) => const TerminalPage()),
    ],
  );
});
