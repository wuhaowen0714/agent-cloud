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
    DioAdapter(dio: dio).onPost(
      '/auth/login',
      (s) => s.reply(200, {
        'access_token': 'a',
        'refresh_token': 'r',
        'user': {'id': 'u1', 'email': 'a@e.com'},
      }),
      data: {'email': 'a@e.com', 'password': 'password123'},
    );
    final store = TokenStore(const FlutterSecureStorage());
    final repo = AuthRepository(dio, store);
    final u = await repo.login('a@e.com', 'password123');
    expect(u.email, 'a@e.com');
    expect(await store.access(), 'a');
    expect(await store.refresh(), 'r');
  });

  test('me:无 access → null(不发请求)', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    final repo = AuthRepository(dio, TokenStore(const FlutterSecureStorage()));
    expect(await repo.me(), isNull);
  });
}
