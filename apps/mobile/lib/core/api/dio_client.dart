import 'package:dio/dio.dart';
import '../storage/token_store.dart';
import 'auth_interceptor.dart';

/// 默认指生产 HTTPS;开发期用 `--dart-define=API_BASE=http://IP:18080/api` 覆盖。
const kBaseUrl = String.fromEnvironment(
  'API_BASE',
  defaultValue: 'https://app.sophclaw.icu:18080/api',
);

Dio buildDio(TokenStore store, {void Function()? onLoggedOut}) {
  final refreshDio = Dio(BaseOptions(baseUrl: kBaseUrl));
  return Dio(BaseOptions(baseUrl: kBaseUrl))
    ..interceptors
        .add(AuthInterceptor(store, refreshDio, onLoggedOut: onLoggedOut));
}
