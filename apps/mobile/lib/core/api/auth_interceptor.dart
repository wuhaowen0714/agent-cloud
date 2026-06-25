import 'package:dio/dio.dart';
import '../storage/token_store.dart';

/// 自动加 Bearer;遇 401 用 refresh 串行换新 token 重试一次。
/// 继承 QueuedInterceptor:并发 401 串行进 onError,天然避免多个请求各自拿同一 refresh 去刷
/// (后端 refresh 一次性轮换 + 重用检测,并发刷新会触发吊销)。
class AuthInterceptor extends QueuedInterceptor {
  AuthInterceptor(this._store, this._refreshDio, {this.onLoggedOut});
  final TokenStore _store;
  final Dio _refreshDio; // 独立 dio(同 baseUrl),刷新请求不被本拦截器再拦
  final void Function()? onLoggedOut;

  @override
  Future<void> onRequest(
      RequestOptions options, RequestInterceptorHandler handler) async {
    final at = await _store.access();
    if (at != null) options.headers['Authorization'] = 'Bearer $at';
    handler.next(options);
  }

  @override
  Future<void> onError(
      DioException err, ErrorInterceptorHandler handler) async {
    if (err.response?.statusCode != 401 ||
        err.requestOptions.extra['retried'] == true) {
      return handler.next(err);
    }
    final rt = await _store.refresh();
    if (rt == null) {
      await _logout();
      return handler.next(err);
    }
    try {
      final r = await _refreshDio
          .post('/auth/refresh', data: {'refresh_token': rt});
      await _store.save(
        access: r.data['access_token'] as String,
        refresh: r.data['refresh_token'] as String,
      );
    } catch (_) {
      await _logout();
      return handler.next(err);
    }
    // 用新 token 重试原请求(标记 retried 防循环),走 refreshDio 避免再被本拦截器拦。
    final o = err.requestOptions..extra['retried'] = true;
    o.headers['Authorization'] = 'Bearer ${await _store.access()}';
    try {
      return handler.resolve(await _refreshDio.fetch(o));
    } on DioException catch (e) {
      return handler.next(e);
    }
  }

  Future<void> _logout() async {
    await _store.clear();
    onLoggedOut?.call();
  }
}
