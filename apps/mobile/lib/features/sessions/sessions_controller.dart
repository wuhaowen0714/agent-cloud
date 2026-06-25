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

  Future<void> refresh() async {
    state = await AsyncValue.guard(
        () => ref.read(sessionsRepoProvider).listSessions());
  }
}

final sessionsControllerProvider =
    AsyncNotifierProvider<SessionsController, List<Session>>(
        SessionsController.new);
