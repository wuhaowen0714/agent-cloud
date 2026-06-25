/// BYOK provider 凭据(api_key 仅 masked 回传,明文不出后端)。
class ProviderCredential {
  final String id;
  final String name;
  final String baseUrl;
  final String masked; // 脱敏后的 key,如 sk-…1234
  final List<String> models;

  const ProviderCredential({
    required this.id,
    required this.name,
    required this.baseUrl,
    required this.masked,
    required this.models,
  });

  factory ProviderCredential.fromJson(Map<String, dynamic> j) =>
      ProviderCredential(
        id: j['id'] as String,
        name: j['name'] as String,
        baseUrl: j['base_url'] as String,
        masked: j['masked'] as String? ?? '',
        models: (j['models'] as List).cast<String>(),
      );
}
