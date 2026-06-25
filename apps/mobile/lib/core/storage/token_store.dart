import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// access/refresh token 的安全存储(iOS Keychain / Android Keystore)。
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
