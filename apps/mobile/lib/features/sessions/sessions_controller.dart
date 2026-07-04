import 'dart:async'; // unawaited

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
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
    // 清该会话持久化的排队消息(防僵尸残留 secure_storage);best-effort。
    unawaited(
        const FlutterSecureStorage().delete(key: 'queue.$id').catchError((_) {}));
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

  /// 重命名会话(PATCH title),就地替换。⚠️ 同 refresh:model 保留本地(前端权威) —— rename 的
  /// 整行响应若与并发 patchModel 乱序落库,其 s.model 可能是旧值,直接整行替换会把 model 盖回。
  Future<void> rename(String id, String title) async {
    final s =
        await ref.read(sessionsRepoProvider).patchSession(id, title: title);
    state = AsyncValue.data([
      for (final x in (state.asData?.value ?? <Session>[]))
        x.id == id ? s.copyWith(model: x.model) : x,
    ]);
  }

  /// 刷新会话列表。⚠️ session.model 是【前端权威】(只由 patchModel 改并落库):全量刷新拉到的
  /// DB 快照可能因 in-flight(与 patchModel 并发)而 stale,绝不能用它覆盖本地 model —— 否则会
  /// 盖掉用户/自动切换刚选的模型。这正是首回合 _pollTitle 反复 refresh 时盖掉手动切换、导致
  /// "切回文本后再发图不再自动切 vision、文本模型收图无法响应"的根因。故 model 一律保留本地,
  /// 其余字段(title/status/活跃时间)用服务器值。
  Future<void> refresh() async {
    state = await AsyncValue.guard(() async {
      final fresh = await ref.read(sessionsRepoProvider).listSessions();
      // 拿到服务器列表后再读本地 model 快照(含刷新期间可能发生的 patchModel),按 id 合并。
      final localModel = {
        for (final s in (state.asData?.value ?? const <Session>[])) s.id: s.model
      };
      return [
        for (final s in fresh)
          localModel.containsKey(s.id)
              ? s.copyWith(model: localModel[s.id]!)
              : s,
      ];
    });
  }

  /// 删除 agent(后端级联删其会话/记忆/文档);随后刷新 agent 列表与会话。
  Future<void> deleteAgent(String id) async {
    await ref.read(sessionsRepoProvider).deleteAgent(id);
    ref.invalidate(agentsProvider);
    await refresh();
  }

  /// 创建 agent → 刷新 agent 列表 → 返回新 agent(供调用方选中 + 跳设置页)。
  Future<AgentConfig> createAgent(String name) async {
    final a = await ref.read(sessionsRepoProvider).createAgent(name);
    ref.invalidate(agentsProvider);
    return a;
  }

  /// 重命名 agent → 刷新 agent 列表。
  Future<void> renameAgent(String id, String name) async {
    await ref.read(sessionsRepoProvider).patchAgentName(id, name);
    ref.invalidate(agentsProvider);
  }
}

final sessionsControllerProvider =
    AsyncNotifierProvider<SessionsController, List<Session>>(
        SessionsController.new);
