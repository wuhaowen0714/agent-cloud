import 'package:dio/dio.dart';
import '../../models/agent_config.dart';
import '../../models/session.dart';

class SessionsRepository {
  SessionsRepository(this._dio);
  final Dio _dio;

  Future<List<AgentConfig>> listAgents() async {
    final r = await _dio.get('/agent-configs');
    return (r.data as List)
        .map((e) => AgentConfig.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<Session>> listSessions() async {
    final r = await _dio.get('/sessions');
    return (r.data as List)
        .map((e) => Session.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Session> createSession(String agentConfigId) async {
    final r =
        await _dio.post('/sessions', data: {'agent_config_id': agentConfigId});
    return Session.fromJson(r.data as Map<String, dynamic>);
  }

  Future<Session> patchSession(String id, {String? model, String? title}) async {
    final r = await _dio.patch('/sessions/$id', data: {
      'model': ?model,
      'title': ?title,
    });
    return Session.fromJson(r.data as Map<String, dynamic>);
  }

  /// 标记会话已读(定时任务产物的未读点;幂等)。
  Future<void> markRead(String id) =>
      _dio.post('/sessions/$id/mark-read');

  Future<void> deleteSession(String id) => _dio.delete('/sessions/$id');

  // 删 agent:后端级联删其全部会话/记忆/文档;有会话在跑 → 409。
  Future<void> deleteAgent(String id) => _dio.delete('/agent-configs/$id');

  // 创建 agent:后端只需 name,返回完整 AgentConfig。
  Future<AgentConfig> createAgent(String name) async {
    final r = await _dio.post('/agent-configs', data: {'name': name});
    return AgentConfig.fromJson(r.data as Map<String, dynamic>);
  }

  // 重命名 agent(PATCH name)。
  Future<AgentConfig> patchAgentName(String id, String name) async {
    final r = await _dio.patch('/agent-configs/$id', data: {'name': name});
    return AgentConfig.fromJson(r.data as Map<String, dynamic>);
  }
}
