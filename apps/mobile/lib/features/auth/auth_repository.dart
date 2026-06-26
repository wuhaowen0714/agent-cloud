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

  /// 启动时探当前登录态:无 access → null;有则 /auth/me。
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
