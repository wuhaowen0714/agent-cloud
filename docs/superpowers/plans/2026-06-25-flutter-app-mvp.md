# Flutter App MVP 实现计划

> **执行方式:** controller 直接 inline 执行(用户要求不开子 agent)。步骤用 checkbox 跟踪;每个 Task 末尾 commit。

**Goal:** agent-cloud 的 Flutter 移动 App(MVP)。本文档覆盖 ① 脚手架 + ② 认证;③~⑦(会话/聊天/多模态/设置/OTA)后续分批补计划。

**Architecture:** feature-first + Riverpod;dio 拦截器自动加 Bearer、401 自动 refresh 重试;token 存 flutter_secure_storage。对标后端 `/auth/*`(refresh 走响应体)。

**Tech Stack:** Flutter 3.41 / flutter_riverpod / dio / flutter_secure_storage / go_router / Material 3(teal)。工程在 `apps/mobile`。

**验证手段:** `flutter analyze`(静态)+ `flutter test`(单元/widget,不需设备)。UI 预览先 Chrome/macOS,Android 模拟器联调。

---

## 文件结构(① + ②)

```
apps/mobile/
  pubspec.yaml                         依赖
  lib/
    main.dart                          ProviderScope + MaterialApp.router
    core/
      theme/app_theme.dart             Material 3 + teal
      router/app_router.dart           go_router(/login /home,authGate 重定向)
      storage/token_store.dart         secure_storage 封装(access/refresh 读写清)
      api/dio_client.dart              dio 实例 + AuthInterceptor(Bearer + 401 refresh)
      api/api_exception.dart           统一异常
    models/
      user.dart                        User
      token_response.dart              TokenResponse(access/refresh/user)
    features/auth/
      auth_repository.dart             register/login/refresh/logout/me
      auth_controller.dart             Riverpod StateNotifier(登录态)
      login_page.dart                  登录/注册页
  test/
    core/storage/token_store_test.dart
    core/api/auth_interceptor_test.dart
    features/auth/auth_repository_test.dart
```

---

## 阶段 ①:脚手架

### Task 1: flutter create + 依赖

**Files:** Create `apps/mobile/`(脚手架);Modify `apps/mobile/pubspec.yaml`

- [ ] **Step 1: 生成工程**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/.worktrees/flutter-app/apps
flutter create --org icu.sophclaw --project-name agent_cloud_mobile --platforms android,ios mobile
```
Expected: `All done!`,生成 `apps/mobile/`。

- [ ] **Step 2: 写依赖到 pubspec**

`apps/mobile/pubspec.yaml` 的 `dependencies:` 段替换为:
```yaml
dependencies:
  flutter:
    sdk: flutter
  flutter_riverpod: ^2.5.1
  dio: ^5.7.0
  flutter_secure_storage: ^9.2.2
  go_router: ^14.6.2
  flutter_markdown: ^0.7.4
  image_picker: ^1.1.2
  package_info_plus: ^8.1.1
  connectivity_plus: ^6.1.0
```

- [ ] **Step 3: 拉依赖 + 静态检查**

Run: `cd apps/mobile && flutter pub get && flutter analyze`
Expected: pub get 成功;analyze 仅模板告警(后续清)。

- [ ] **Step 4: Commit**
```bash
git add apps/mobile
git commit -m "feat(mobile): flutter 脚手架 + 依赖"
```

### Task 2: teal 主题

**Files:** Create `apps/mobile/lib/core/theme/app_theme.dart`

- [ ] **Step 1: 写主题**(对标 web 浅色 + teal)
```dart
import 'package:flutter/material.dart';

/// 对标 web 的浅色 + teal 主色。
class AppTheme {
  static const _seed = Color(0xFF0D9488); // teal-600

  static ThemeData light() => ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: _seed),
        scaffoldBackgroundColor: const Color(0xFFF8FAFC), // slate-50
      );
}
```

- [ ] **Step 2: analyze**
Run: `cd apps/mobile && flutter analyze lib/core/theme/app_theme.dart`
Expected: No issues。

- [ ] **Step 3: Commit**
```bash
git add apps/mobile/lib/core/theme/app_theme.dart
git commit -m "feat(mobile): teal 主题"
```

### Task 3: go_router 骨架 + main

**Files:** Create `apps/mobile/lib/core/router/app_router.dart`;Modify `apps/mobile/lib/main.dart`

- [ ] **Step 1: 路由骨架**(占位 /login /home,登录态重定向待 auth_controller 接入)
```dart
import 'package:go_router/go_router.dart';
import 'package:flutter/material.dart';

GoRouter buildRouter() => GoRouter(
      initialLocation: '/login',
      routes: [
        GoRoute(path: '/login', builder: (_, __) => const _Placeholder('Login')),
        GoRoute(path: '/home', builder: (_, __) => const _Placeholder('Home')),
      ],
    );

class _Placeholder extends StatelessWidget {
  final String label;
  const _Placeholder(this.label);
  @override
  Widget build(BuildContext context) =>
      Scaffold(body: Center(child: Text(label)));
}
```

- [ ] **Step 2: main.dart**
```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'core/router/app_router.dart';
import 'core/theme/app_theme.dart';

void main() => runApp(const ProviderScope(child: App()));

class App extends StatelessWidget {
  const App({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp.router(
        title: 'Agent Cloud',
        theme: AppTheme.light(),
        routerConfig: buildRouter(),
      );
}
```

- [ ] **Step 3: 跑起来**
Run: `cd apps/mobile && flutter analyze && flutter test`
Expected: analyze 干净;默认 widget_test 可能因改了 main 失败 → 下一步修。

- [ ] **Step 4: 修默认 widget_test**(模板的 counter 测试已不适用,替换为冒烟测试)
`apps/mobile/test/widget_test.dart`:
```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:agent_cloud_mobile/main.dart';

void main() {
  testWidgets('App 启动到 Login 占位', (tester) async {
    await tester.pumpWidget(const ProviderScope(child: App()));
    expect(find.text('Login'), findsOneWidget);
  });
}
```
Run: `flutter test` → Expected: PASS。

- [ ] **Step 5: Commit**
```bash
git add apps/mobile/lib/main.dart apps/mobile/lib/core/router apps/mobile/test/widget_test.dart
git commit -m "feat(mobile): go_router 骨架 + main + 冒烟测试"
```

---

## 阶段 ②:认证

### Task 4: token 存储(secure_storage)

**Files:** Create `apps/mobile/lib/core/storage/token_store.dart`;Test `apps/mobile/test/core/storage/token_store_test.dart`

- [ ] **Step 1: 接口 + 实现**
```dart
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// access/refresh token 的安全存储(Keychain/Keystore)。
class TokenStore {
  TokenStore(this._s);
  final FlutterSecureStorage _s;
  static const _kAccess = 'access_token';
  static const _kRefresh = 'refresh_token';

  Future<void> save({required String access, required String refresh}) async {
    await _s.write(key: _kAccess, value: access);
    await _s.write(key: _kRefresh, value: refresh);
  }

  Future<String?> access() => _s.read(key: _kAccess);
  Future<String?> refresh() => _s.read(key: _kRefresh);
  Future<void> clear() async {
    await _s.delete(key: _kAccess);
    await _s.delete(key: _kRefresh);
  }
}
```

- [ ] **Step 2: 测试**(用内存假 storage,不碰真 Keychain)
```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:agent_cloud_mobile/core/storage/token_store.dart';

void main() {
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

  test('save/read/clear', () async {
    final store = TokenStore(const FlutterSecureStorage());
    await store.save(access: 'a1', refresh: 'r1');
    expect(await store.access(), 'a1');
    expect(await store.refresh(), 'r1');
    await store.clear();
    expect(await store.access(), isNull);
  });
}
```
Run: `flutter test test/core/storage/token_store_test.dart` → Expected: PASS。

- [ ] **Step 3: Commit**

### Task 5: 数据模型(User / TokenResponse)

**Files:** Create `apps/mobile/lib/models/user.dart`、`apps/mobile/lib/models/token_response.dart`

- [ ] **Step 1: User**
```dart
class User {
  final String id;
  final String email;
  const User({required this.id, required this.email});
  factory User.fromJson(Map<String, dynamic> j) =>
      User(id: j['id'] as String, email: j['email'] as String);
}
```

- [ ] **Step 2: TokenResponse**(对标后端 body:access_token / refresh_token / user)
```dart
import 'user.dart';

class TokenResponse {
  final String accessToken;
  final String refreshToken;
  final User user;
  const TokenResponse(
      {required this.accessToken, required this.refreshToken, required this.user});
  factory TokenResponse.fromJson(Map<String, dynamic> j) => TokenResponse(
        accessToken: j['access_token'] as String,
        refreshToken: j['refresh_token'] as String,
        user: User.fromJson(j['user'] as Map<String, dynamic>),
      );
}
```

- [ ] **Step 3: Commit**

### Task 6: dio client + AuthInterceptor(Bearer + 401 refresh)

**Files:** Create `apps/mobile/lib/core/api/dio_client.dart`、`apps/mobile/lib/core/api/api_exception.dart`;Test `apps/mobile/test/core/api/auth_interceptor_test.dart`

- [ ] **Step 1: api_exception**
```dart
class ApiException implements Exception {
  final int? status;
  final String message;
  ApiException(this.message, {this.status});
  @override
  String toString() => 'ApiException($status): $message';
}
```

- [ ] **Step 2: AuthInterceptor**(核心:请求加 Bearer;401 → 用 refresh 换新 token 重试;**刷新串行化**防并发双花;refresh 也失败 → 清存储 + 抛)
```dart
import 'dart:async';
import 'package:dio/dio.dart';
import '../storage/token_store.dart';

/// 自动加 Bearer;遇 401 用 refresh 串行换新 token 重试一次。
class AuthInterceptor extends QueuedInterceptor {
  AuthInterceptor(this._store, this._refreshDio, {required this.baseUrl, this.onLoggedOut});
  final TokenStore _store;
  final Dio _refreshDio; // 独立 dio,避免刷新请求再被本拦截器拦
  final String baseUrl;
  final void Function()? onLoggedOut;

  @override
  Future<void> onRequest(RequestOptions o, RequestInterceptorHandler h) async {
    final at = await _store.access();
    if (at != null) o.headers['Authorization'] = 'Bearer $at';
    h.next(o);
  }

  @override
  Future<void> onError(DioException e, ErrorInterceptorHandler h) async {
    if (e.response?.statusCode != 401 || e.requestOptions.extra['retried'] == true) {
      return h.next(e);
    }
    final rt = await _store.refresh();
    if (rt == null) {
      await _store.clear();
      onLoggedOut?.call();
      return h.next(e);
    }
    try {
      final r = await _refreshDio.post('$baseUrl/auth/refresh',
          data: {'refresh_token': rt});
      await _store.save(
          access: r.data['access_token'], refresh: r.data['refresh_token']);
    } catch (_) {
      await _store.clear();
      onLoggedOut?.call();
      return h.next(e);
    }
    // 用新 token 重试原请求(标记 retried 防循环)
    final o = e.requestOptions..extra['retried'] = true;
    o.headers['Authorization'] = 'Bearer ${await _store.access()}';
    try {
      final clone = await _refreshDio.fetch(o);
      return h.resolve(clone);
    } on DioException catch (err) {
      return h.next(err);
    }
  }
}
```
> QueuedInterceptor 让并发 401 串行进 onError,天然串行化刷新(spec 要求)。

- [ ] **Step 3: dio_client**(组装 dio + 拦截器)
```dart
import 'package:dio/dio.dart';
import '../storage/token_store.dart';
import 'auth_interceptor.dart';

const kBaseUrl = String.fromEnvironment('API_BASE',
    defaultValue: 'https://app.sophclaw.icu:18080/api');

Dio buildDio(TokenStore store, {void Function()? onLoggedOut}) {
  final refreshDio = Dio(BaseOptions(baseUrl: kBaseUrl));
  final dio = Dio(BaseOptions(baseUrl: kBaseUrl))
    ..interceptors.add(AuthInterceptor(store, refreshDio,
        baseUrl: kBaseUrl, onLoggedOut: onLoggedOut));
  return dio;
}
```
(注:auth_interceptor.dart 即 Step 2 的文件,拆出去:`apps/mobile/lib/core/api/auth_interceptor.dart`)

- [ ] **Step 4: 拦截器测试**(用 DioAdapter/MockAdapter 模拟 401→refresh→重试)
```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/core/storage/token_store.dart';
import 'package:agent_cloud_mobile/core/api/auth_interceptor.dart';

void main() {
  setUp(() => FlutterSecureStorage.setMockInitialValues(
      {'access_token': 'old', 'refresh_token': 'r1'}));

  test('401 → refresh → 重试成功', () async {
    final store = TokenStore(const FlutterSecureStorage());
    final refreshDio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'))
      ..interceptors.add(AuthInterceptor(store, refreshDio, baseUrl: 'http://x/api'));
    final adapter = DioAdapter(dio: dio);
    final radapter = DioAdapter(dio: refreshDio);
    // 第一次 /me 带 old → 401;refresh 返回新 token;重试 /me 带 new → 200
    adapter.onGet('/me', (s) => s.reply(401, {}), headers: {'Authorization': 'Bearer old'});
    radapter.onPost('/auth/refresh', (s) => s.reply(200,
        {'access_token': 'new', 'refresh_token': 'r2'}), data: {'refresh_token': 'r1'});
    radapter.onGet('/me', (s) => s.reply(200, {'ok': true}),
        headers: {'Authorization': 'Bearer new'});
    final res = await dio.get('/me');
    expect(res.statusCode, 200);
    expect(await store.access(), 'new');
  });
}
```
> 需在 pubspec dev_dependencies 加 `http_mock_adapter: ^0.6.1`。
Run: `flutter test test/core/api/auth_interceptor_test.dart` → Expected: PASS。

- [ ] **Step 5: Commit**

### Task 7: auth_repository

**Files:** Create `apps/mobile/lib/features/auth/auth_repository.dart`;Test `apps/mobile/test/features/auth/auth_repository_test.dart`

- [ ] **Step 1: repository**(register/login 存 token;logout 带 body refresh;me)
```dart
import 'package:dio/dio.dart';
import '../../core/storage/token_store.dart';
import '../../models/token_response.dart';
import '../../models/user.dart';

class AuthRepository {
  AuthRepository(this._dio, this._store);
  final Dio _dio;
  final TokenStore _store;

  Future<User> register(String email, String pw) =>
      _auth('/auth/register', email, pw);
  Future<User> login(String email, String pw) =>
      _auth('/auth/login', email, pw);

  Future<User> _auth(String path, String email, String pw) async {
    final r = await _dio.post(path, data: {'email': email, 'password': pw});
    final t = TokenResponse.fromJson(r.data as Map<String, dynamic>);
    await _store.save(access: t.accessToken, refresh: t.refreshToken);
    return t.user;
  }

  Future<User?> me() async {
    if (await _store.access() == null) return null;
    final r = await _dio.get('/auth/me');
    return User.fromJson(r.data as Map<String, dynamic>);
  }

  Future<void> logout() async {
    final rt = await _store.refresh();
    if (rt != null) {
      try {
        await _dio.post('/auth/logout', data: {'refresh_token': rt});
      } catch (_) {}
    }
    await _store.clear();
  }
}
```

- [ ] **Step 2: 测试**(mock adapter:login 存 token;me 返回 user)
```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/core/storage/token_store.dart';
import 'package:agent_cloud_mobile/features/auth/auth_repository.dart';

void main() {
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

  test('login 存 token + 返回 user', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onPost('/auth/login', (s) => s.reply(200, {
          'access_token': 'a', 'refresh_token': 'r',
          'user': {'id': 'u1', 'email': 'a@e.com'}
        }), data: {'email': 'a@e.com', 'password': 'password123'});
    final store = TokenStore(const FlutterSecureStorage());
    final repo = AuthRepository(dio, store);
    final u = await repo.login('a@e.com', 'password123');
    expect(u.email, 'a@e.com');
    expect(await store.access(), 'a');
  });
}
```
Run: `flutter test test/features/auth/auth_repository_test.dart` → Expected: PASS。

- [ ] **Step 3: Commit**

### Task 8: auth_controller(Riverpod) + 路由接入

**Files:** Create `apps/mobile/lib/features/auth/auth_controller.dart`;Modify `apps/mobile/lib/core/router/app_router.dart`

- [ ] **Step 1: providers + controller**
```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../../core/storage/token_store.dart';
import '../../core/api/dio_client.dart';
import '../../models/user.dart';
import 'auth_repository.dart';

final tokenStoreProvider = Provider((_) => TokenStore(const FlutterSecureStorage()));
final dioProvider = Provider((ref) => buildDio(ref.read(tokenStoreProvider)));
final authRepoProvider = Provider(
    (ref) => AuthRepository(ref.read(dioProvider), ref.read(tokenStoreProvider)));

/// 登录态:null=未登录;User=已登录。bootstrap 启动时 me() 探一次。
class AuthController extends StateNotifier<AsyncValue<User?>> {
  AuthController(this._repo) : super(const AsyncValue.loading()) {
    _bootstrap();
  }
  final AuthRepository _repo;

  Future<void> _bootstrap() async {
    state = await AsyncValue.guard(() => _repo.me());
  }

  Future<void> login(String email, String pw) async {
    state = await AsyncValue.guard(() => _repo.login(email, pw).then((u) => u));
  }

  Future<void> register(String email, String pw) async {
    state = await AsyncValue.guard(() => _repo.register(email, pw).then((u) => u));
  }

  Future<void> logout() async {
    await _repo.logout();
    state = const AsyncValue.data(null);
  }
}

final authControllerProvider =
    StateNotifierProvider<AuthController, AsyncValue<User?>>(
        (ref) => AuthController(ref.read(authRepoProvider)));
```

- [ ] **Step 2: 路由接 authGate**(已登录在 /login → 跳 /home;未登录在 /home → 跳 /login)
```dart
import 'package:go_router/go_router.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../features/auth/auth_controller.dart';
import '../../features/auth/login_page.dart';

GoRouter buildRouter(Ref ref) => GoRouter(
      initialLocation: '/home',
      redirect: (ctx, state) {
        final auth = ref.read(authControllerProvider);
        final loggedIn = auth.valueOrNull != null;
        final atLogin = state.matchedLocation == '/login';
        if (!loggedIn) return atLogin ? null : '/login';
        if (atLogin) return '/home';
        return null;
      },
      routes: [
        GoRoute(path: '/login', builder: (_, __) => const LoginPage()),
        GoRoute(path: '/home', builder: (_, __) => const _HomePlaceholder()),
      ],
    );

class _HomePlaceholder extends StatelessWidget {
  const _HomePlaceholder();
  @override
  Widget build(BuildContext context) =>
      const Scaffold(body: Center(child: Text('Home(会话列表占位)')));
}
```
> main.dart 改为 `Consumer` 取 ref 传 buildRouter(见 Step 3)。

- [ ] **Step 3: main.dart 接 ref**
```dart
class App extends ConsumerWidget {
  const App({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) => MaterialApp.router(
        title: 'Agent Cloud',
        theme: AppTheme.light(),
        routerConfig: buildRouter(ref),
      );
}
```

- [ ] **Step 4: analyze**(此时 login_page 还没建 → 先建 Task 9 再 analyze;或先占位)
- [ ] **Step 5: Commit**

### Task 9: 登录/注册页

**Files:** Create `apps/mobile/lib/features/auth/login_page.dart`;Test `apps/mobile/test/features/auth/login_page_test.dart`

- [ ] **Step 1: 页面**(邮箱密码 + 登录/注册切换 + loading/error)
```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'auth_controller.dart';

class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});
  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  final _email = TextEditingController();
  final _pw = TextEditingController();
  bool _register = false;
  bool _busy = false;
  String? _err;

  Future<void> _submit() async {
    setState(() { _busy = true; _err = null; });
    final c = ref.read(authControllerProvider.notifier);
    try {
      if (_register) {
        await c.register(_email.text.trim(), _pw.text);
      } else {
        await c.login(_email.text.trim(), _pw.text);
      }
      // 登录失败时 controller state 会是 error;这里读一次
      final s = ref.read(authControllerProvider);
      if (s.hasError) setState(() => _err = '邮箱或密码错误');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        body: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 360),
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                Text(_register ? '注册' : '登录',
                    style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 24),
                TextField(controller: _email,
                    decoration: const InputDecoration(labelText: '邮箱'),
                    keyboardType: TextInputType.emailAddress),
                const SizedBox(height: 12),
                TextField(controller: _pw, obscureText: true,
                    decoration: const InputDecoration(labelText: '密码')),
                if (_err != null) ...[
                  const SizedBox(height: 12),
                  Text(_err!, style: const TextStyle(color: Colors.red)),
                ],
                const SizedBox(height: 24),
                FilledButton(
                    onPressed: _busy ? null : _submit,
                    child: Text(_busy ? '...' : (_register ? '注册' : '登录'))),
                TextButton(
                    onPressed: () => setState(() => _register = !_register),
                    child: Text(_register ? '已有账号?去登录' : '没有账号?去注册')),
              ]),
            ),
          ),
        ),
      );
}
```

- [ ] **Step 2: widget 测试**(渲染 + 切换注册/登录)
```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:agent_cloud_mobile/features/auth/login_page.dart';

void main() {
  testWidgets('登录页渲染 + 切到注册', (tester) async {
    await tester.pumpWidget(const ProviderScope(
        child: MaterialApp(home: LoginPage())));
    expect(find.text('登录'), findsWidgets);
    await tester.tap(find.text('没有账号?去注册'));
    await tester.pump();
    expect(find.text('注册'), findsWidgets);
  });
}
```
Run: `flutter test test/features/auth/login_page_test.dart` → Expected: PASS。

- [ ] **Step 3: 全量 analyze + test**
Run: `cd apps/mobile && flutter analyze && flutter test`
Expected: analyze 干净;全部测试 PASS。

- [ ] **Step 4: Commit**

---

## ③~⑦ 后续(本批次完成后补详细计划)

- ③ 会话列表:agentConfigs + sessions repository/provider + 列表 UI + 增删
- ④ 聊天 + 回合流(核心):models + 移植 blocks 逻辑 + SSE 自解析 + 聊天页 + resume 重连 + 发送重试
- ⑤ 多模态发图:image_picker + turn/stream images
- ⑥ 设置:模型选择 + 登出
- ⑦ OTA:后端 /app/version + nginx APK + core/update + 发版脚本

## 注意

- `flutter_secure_storage` 测试用 `setMockInitialValues` 走内存,不碰真 Keychain。
- 拦截器测试需 `http_mock_adapter`(dev_dependencies)。
- Android 连明文(开发期指本地)需 `network_security_config`;默认 baseUrl 已指 https 生产,开发期用 `--dart-define=API_BASE=...` 覆盖。
- refresh 并发用 `QueuedInterceptor` 天然串行,避免后端重用吊销。
