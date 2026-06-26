import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// access/refresh token 的安全存储(iOS Keychain / Android Keystore)。
///
/// 带内存缓存:写入后立即可读,绕开 Android secure storage 首次 write-then-read
/// 的偶发延迟(新装登录后首个请求拿不到 token → 没带 Bearer → 401 的根因)。
/// 重启后内存为空,首次读回退到 storage(此时 Keystore 已就绪),读到后回填内存。
class TokenStore {
  TokenStore(this._s);
  final FlutterSecureStorage _s;
  static const _kAccess = 'access_token';
  static const _kRefresh = 'refresh_token';

  String? _access;
  String? _refresh;

  Future<void> save({required String access, required String refresh}) async {
    _access = access;
    _refresh = refresh;
    await _s.write(key: _kAccess, value: access);
    await _s.write(key: _kRefresh, value: refresh);
  }

  // 不能写成 `_access ??= await read`:它的 null 检查在 await 之前,await 期间若 save()
  // 写入了 token,await 返回的旧值(null)会无条件覆盖它(新装登录 race → 401 的真因)。
  // 正确:await 之后再 ??= 回填,只在仍为空时填,绝不覆盖并发写入的值。
  Future<String?> access() async {
    if (_access != null) return _access;
    final v = await _s.read(key: _kAccess);
    return _access ??= v;
  }

  Future<String?> refresh() async {
    if (_refresh != null) return _refresh;
    final v = await _s.read(key: _kRefresh);
    return _refresh ??= v;
  }

  Future<void> clear() async {
    _access = null;
    _refresh = null;
    await _s.delete(key: _kAccess);
    await _s.delete(key: _kRefresh);
  }
}
