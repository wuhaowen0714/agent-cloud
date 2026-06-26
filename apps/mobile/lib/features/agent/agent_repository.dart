import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../auth/auth_controller.dart'; // dioProvider
import '../../models/skill.dart';
import '../../models/context_document.dart';

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

  /// agent 人设(AGENTS 文档)内容;无则空串。
  Future<String> getAgentInstructions(String agentId) async {
    final r = await _dio.get('/context-documents',
        queryParameters: {'scope': 'agent', 'agent_id': agentId});
    final docs = (r.data as List)
        .map((e) => ContextDocument.fromJson(e as Map<String, dynamic>))
        .where((d) => d.type == 'AGENTS');
    return docs.isEmpty ? '' : docs.first.content;
  }

  /// 写 agent 人设(AGENTS)。
  Future<void> putAgentInstructions(String agentId, String content) =>
      _dio.put('/context-documents', data: {
        'scope': 'agent',
        'type': 'AGENTS',
        'content': content,
        'agent_id': agentId,
      });

  /// agent 专属记忆(scope=agent)读;无则空串。
  Future<String> getAgentMemory(String agentId) async {
    final r = await _dio.get('/memory',
        queryParameters: {'scope': 'agent', 'agent_id': agentId});
    return (r.data as Map<String, dynamic>)['content'] as String? ?? '';
  }

  Future<void> putAgentMemory(String agentId, String content) =>
      _dio.put('/memory',
          data: {'scope': 'agent', 'content': content, 'agent_id': agentId});

  Future<void> clearAgentMemory(String agentId) => _dio.delete('/memory',
      queryParameters: {'scope': 'agent', 'agent_id': agentId});
}

final agentRepoProvider =
    Provider((ref) => AgentRepository(ref.read(dioProvider)));

/// agent 当前启用的技能集合(autoDispose 缓存)。
final agentSkillsProvider =
    FutureProvider.autoDispose.family<List<Skill>, String>(
        (ref, agentId) => ref.read(agentRepoProvider).getAgentSkills(agentId));
