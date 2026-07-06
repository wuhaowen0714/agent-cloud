import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/scheduled_task.dart';
import '../auth/auth_controller.dart'; // dioProvider

/// 值守中心:定时任务的增删改查 + 立即运行(backend /scheduled-tasks)。
class WatchRepository {
  WatchRepository(this._dio);
  final Dio _dio;

  Future<List<ScheduledTask>> list() async {
    final r = await _dio.get('/scheduled-tasks');
    return (r.data as List)
        .map((e) => ScheduledTask.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<ScheduledTask> create({
    required String name,
    required String prompt,
    required String agentConfigId,
    required String scheduleKind,
    required String scheduleExpr,
  }) async {
    final r = await _dio.post('/scheduled-tasks', data: {
      'name': name,
      'prompt': prompt,
      'agent_config_id': agentConfigId,
      'schedule_kind': scheduleKind,
      'schedule_expr': scheduleExpr,
    });
    return ScheduledTask.fromJson(r.data as Map<String, dynamic>);
  }

  Future<ScheduledTask> setEnabled(String id, bool enabled) async {
    final r =
        await _dio.patch('/scheduled-tasks/$id', data: {'enabled': enabled});
    return ScheduledTask.fromJson(r.data as Map<String, dynamic>);
  }

  Future<void> delete(String id) => _dio.delete('/scheduled-tasks/$id');

  /// 立即运行一次(不等下个周期;结果照常落新会话 + 推送)。
  Future<ScheduledTask> runNow(String id) async {
    final r = await _dio.post('/scheduled-tasks/$id/run-now');
    return ScheduledTask.fromJson(r.data as Map<String, dynamic>);
  }
}

final watchRepoProvider =
    Provider<WatchRepository>((ref) => WatchRepository(ref.read(dioProvider)));

final watchTasksProvider = FutureProvider.autoDispose<List<ScheduledTask>>(
    (ref) => ref.read(watchRepoProvider).list());
