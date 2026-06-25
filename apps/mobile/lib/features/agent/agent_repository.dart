import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../auth/auth_controller.dart'; // dioProvider
import '../../models/skill.dart';

/// agent 配置:工具开关(enabled_tools)与技能启用集(全量替换)。
class AgentRepository {
  AgentRepository(this._dio);
  final Dio _dio;

  Future<void> patchTools(String agentId, List<String> enabledTools) =>
      _dio.patch('/agent-configs/$agentId',
          data: {'enabled_tools': enabledTools});

  Future<List<Skill>> getAgentSkills(String agentId) async {
    final r = await _dio.get('/agent-configs/$agentId/skills');
    return (r.data as List)
        .map((e) => Skill.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> setAgentSkills(String agentId, List<String> skillIds) =>
      _dio.put('/agent-configs/$agentId/skills', data: {'skill_ids': skillIds});
}

final agentRepoProvider =
    Provider((ref) => AgentRepository(ref.read(dioProvider)));

/// agent 当前启用的技能集合(autoDispose 缓存)。
final agentSkillsProvider =
    FutureProvider.autoDispose.family<List<Skill>, String>(
        (ref, agentId) => ref.read(agentRepoProvider).getAgentSkills(agentId));
