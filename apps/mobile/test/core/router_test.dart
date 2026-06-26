import 'package:flutter_test/flutter_test.dart';
import 'package:agent_cloud_mobile/core/router/app_router.dart';

void main() {
  group('authRedirect', () {
    test('bootstrap(isLoading)去 splash —— 绝不停 home(否则发无 token 请求 → 401 真因)',
        () {
      // 这是 401 根因的回归测试:旧逻辑 isLoading 时 return null 停在 /home
      expect(authRedirect(isLoading: true, loggedIn: false, location: '/home'),
          '/splash');
      expect(
          authRedirect(isLoading: true, loggedIn: false, location: '/splash'),
          isNull);
    });

    test('已登录:从 splash/login 进 home,其它页不动', () {
      expect(
          authRedirect(isLoading: false, loggedIn: true, location: '/splash'),
          '/home');
      expect(authRedirect(isLoading: false, loggedIn: true, location: '/login'),
          '/home');
      expect(authRedirect(isLoading: false, loggedIn: true, location: '/home'),
          isNull);
      expect(authRedirect(isLoading: false, loggedIn: true, location: '/files'),
          isNull);
    });

    test('未登录:去 login', () {
      expect(authRedirect(isLoading: false, loggedIn: false, location: '/home'),
          '/login');
      expect(
          authRedirect(isLoading: false, loggedIn: false, location: '/login'),
          isNull);
    });
  });
}
