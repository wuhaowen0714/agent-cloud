import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/core/storage/token_store.dart';
import 'package:agent_cloud_mobile/core/api/auth_interceptor.dart';

void main() {
  setUp(() => FlutterSecureStorage.setMockInitialValues(
      {'access_token': 'old', 'refresh_token': 'r1'}));

  test('401 → refresh → 重试成功,新 token 落库', () async {
    final store = TokenStore(const FlutterSecureStorage());
    final refreshDio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'))
      ..interceptors.add(AuthInterceptor(store, refreshDio));
    final adapter = DioAdapter(dio: dio);
    final radapter = DioAdapter(dio: refreshDio);
    // 首次 /me → 401;refresh 换新 token;重试 /me(走 refreshDio)→ 200
    adapter.onGet('/me', (s) => s.reply(401, {}));
    radapter.onPost('/auth/refresh',
        (s) => s.reply(200, {'access_token': 'new', 'refresh_token': 'r2'}),
        data: {'refresh_token': 'r1'});
    radapter.onGet('/me', (s) => s.reply(200, {'ok': true}));

    final res = await dio.get('/me');
    expect(res.statusCode, 200);
    expect(await store.access(), 'new');
    expect(await store.refresh(), 'r2');
  });

  test('refresh 也失败 → 清存储', () async {
    final store = TokenStore(const FlutterSecureStorage());
    final refreshDio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'))
      ..interceptors.add(AuthInterceptor(store, refreshDio));
    DioAdapter(dio: dio).onGet('/me', (s) => s.reply(401, {}));
    DioAdapter(dio: refreshDio)
        .onPost('/auth/refresh', (s) => s.reply(401, {}));

    await expectLater(dio.get('/me'), throwsA(isA<DioException>()));
    expect(await store.access(), isNull);
  });
}
