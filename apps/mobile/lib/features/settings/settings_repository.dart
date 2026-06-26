import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../auth/auth_controller.dart'; // dioProvider
import '../../models/credential.dart';
import '../../models/skill.dart';

/// 设置相关后端调用:BYOK 凭据 / 用户记忆 / 技能。
class SettingsRepository {
  SettingsRepository(this._dio);
  final Dio _dio;

  // ── BYOK 凭据 ──
  Future<List<ProviderCredential>> listCredentials() async {
    final r = await _dio.get('/credentials');
    return (r.data as List)
        .map((e) => ProviderCredential.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> createCredential({
    required String name,
    required String baseUrl,
    required String apiKey,
    required List<String> models,
  }) =>
      _dio.post('/credentials', data: {
        'name': name,
        'base_url': baseUrl,
        'api_key': apiKey,
        'models': models,
      });

  Future<void> deleteCredential(String id) => _dio.delete('/credentials/$id');

  // ── 用户记忆(user scope,跨 agent)──
  Future<String> getMemory() async {
    final r = await _dio.get('/memory', queryParameters: {'scope': 'user'});
    return (r.data as Map<String, dynamic>)['content'] as String? ?? '';
  }

  Future<void> putMemory(String content) => _dio.put('/memory',
      data: {'scope': 'user', 'content': content, 'agent_id': null});

  Future<void> clearMemory() =>
      _dio.delete('/memory', queryParameters: {'scope': 'user'});

  // ── 技能 ──
  Future<List<Skill>> listSkills() async {
    final r = await _dio.get('/skills');
    return (r.data as List)
        .map((e) => Skill.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> deleteSkill(String id) => _dio.delete('/skills/$id');
}

final settingsRepoProvider =
    Provider((ref) => SettingsRepository(ref.read(dioProvider)));
