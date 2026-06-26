import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../auth/auth_controller.dart'; // dioProvider
import '../../models/agent_config.dart';
import '../../models/session.dart';
import 'sessions_repository.dart';

final sessionsRepoProvider =
    Provider((ref) => SessionsRepository(ref.read(dioProvider)));

/// agent 列表(新建会话时选归属)。
final agentsProvider = FutureProvider<List<AgentConfig>>(
    (ref) => ref.read(sessionsRepoProvider).listAgents());

/// 会话列表 + 增删。
class SessionsController extends AsyncNotifier<List<Session>> {
  @override
  Future<List<Session>> build() =>
      ref.read(sessionsRepoProvider).listSessions();

  Future<Session> create(String agentConfigId) async {
    final s = await ref.read(sessionsRepoProvider).createSession(agentConfigId);
    state = AsyncValue.data([s, ...?state.asData?.value]);
    return s;
  }

  Future<void> remove(String id) async {
    await ref.read(sessionsRepoProvider).deleteSession(id);
    state = AsyncValue.data(
        [...?state.asData?.value.where((s) => s.id != id)]);
  }

  /// 切换会话模型(PATCH session),就地替换列表中对应项。
  Future<void> patchModel(String id, String model) async {
    final s =
        await ref.read(sessionsRepoProvider).patchSession(id, model: model);
    state = AsyncValue.data([
      for (final x in (state.asData?.value ?? <Session>[]))
        x.id == id ? s : x,
    ]);
  }

  /// 重命名会话(PATCH title),就地替换。
  Future<void> rename(String id, String title) async {
    final s =
        await ref.read(sessionsRepoProvider).patchSession(id, title: title);
    state = AsyncValue.data([
      for (final x in (state.asData?.value ?? <Session>[]))
        x.id == id ? s : x,
    ]);
  }

  Future<void> refresh() async {
    state = await AsyncValue.guard(
        () => ref.read(sessionsRepoProvider).listSessions());
  }

  /// 删除 agent(后端级联删其会话/记忆/文档);随后刷新 agent 列表与会话。
  Future<void> deleteAgent(String id) async {
    await ref.read(sessionsRepoProvider).deleteAgent(id);
    ref.invalidate(agentsProvider);
    await refresh();
  }
}

final sessionsControllerProvider =
    AsyncNotifierProvider<SessionsController, List<Session>>(
        SessionsController.new);
