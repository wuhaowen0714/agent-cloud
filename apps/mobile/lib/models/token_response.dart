import 'user.dart';

/// 对标后端 /auth/* 响应体:access_token / refresh_token / user。
class TokenResponse {
  final String accessToken;
  final String refreshToken;
  final User user;
  const TokenResponse({
    required this.accessToken,
    required this.refreshToken,
    required this.user,
  });

  factory TokenResponse.fromJson(Map<String, dynamic> j) => TokenResponse(
        accessToken: j['access_token'] as String,
        refreshToken: j['refresh_token'] as String,
        user: User.fromJson(j['user'] as Map<String, dynamic>),
      );
}
