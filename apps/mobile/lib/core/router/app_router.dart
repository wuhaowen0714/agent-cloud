import 'package:go_router/go_router.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../features/auth/auth_controller.dart';
import '../../features/auth/login_page.dart';
import '../../features/sessions/home_page.dart';
import '../../features/settings/settings_page.dart';
import '../../features/settings/credentials_page.dart';
import '../../features/settings/memory_page.dart';
import '../../features/settings/skills_page.dart';
import '../../features/chat/chat_page.dart';

/// router 作为 provider 缓存(稳定);监听登录态变化 → refresh 重新 redirect。
final routerProvider = Provider<GoRouter>((ref) {
  final refresh = ValueNotifier(0);
  ref.listen(authControllerProvider, (_, _) => refresh.value++);
  ref.onDispose(refresh.dispose);
  return GoRouter(
    refreshListenable: refresh,
    initialLocation: '/home',
    redirect: (ctx, state) {
      final auth = ref.read(authControllerProvider);
      if (auth.isLoading) return null; // bootstrap 中,先不跳
      final loggedIn = auth.asData?.value != null;
      final atLogin = state.matchedLocation == '/login';
      if (!loggedIn) return atLogin ? null : '/login';
      if (atLogin) return '/home';
      return null;
    },
    routes: [
      GoRoute(path: '/login', builder: (_, _) => const LoginPage()),
      GoRoute(path: '/home', builder: (_, _) => const HomePage()),
      GoRoute(
        path: '/chat/:sid',
        builder: (_, st) => ChatPage(st.pathParameters['sid']!),
      ),
      GoRoute(path: '/settings', builder: (_, _) => const SettingsPage()),
      GoRoute(
          path: '/settings/credentials',
          builder: (_, _) => const CredentialsPage()),
      GoRoute(
          path: '/settings/memory', builder: (_, _) => const MemoryPage()),
      GoRoute(
          path: '/settings/skills', builder: (_, _) => const SkillsPage()),
    ],
  );
});
