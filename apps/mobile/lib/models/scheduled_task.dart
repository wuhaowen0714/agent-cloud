/// 值守任务(定时任务):backend scheduled_tasks 的 app 侧模型。
class ScheduledTask {
  final String id;
  final String agentConfigId;
  final String name;
  final String prompt;
  final String scheduleKind; // once | interval | cron
  final String scheduleExpr;
  final bool enabled;
  final DateTime? nextRunAt;
  final DateTime? lastRunAt;
  final String? lastStatus; // ok | error | skipped
  final String? lastError;

  const ScheduledTask({
    required this.id,
    required this.agentConfigId,
    required this.name,
    required this.prompt,
    required this.scheduleKind,
    required this.scheduleExpr,
    required this.enabled,
    this.nextRunAt,
    this.lastRunAt,
    this.lastStatus,
    this.lastError,
  });

  factory ScheduledTask.fromJson(Map<String, dynamic> j) => ScheduledTask(
        id: j['id'] as String,
        agentConfigId: j['agent_config_id'] as String,
        name: j['name'] as String,
        prompt: j['prompt'] as String,
        scheduleKind: j['schedule_kind'] as String,
        scheduleExpr: j['schedule_expr'] as String,
        enabled: j['enabled'] as bool? ?? true,
        nextRunAt: _ts(j['next_run_at']),
        lastRunAt: _ts(j['last_run_at']),
        lastStatus: j['last_status'] as String?,
        lastError: j['last_error'] as String?,
      );

  static DateTime? _ts(dynamic v) =>
      v is String ? DateTime.tryParse(v)?.toLocal() : null;

  /// 周期的人话描述(列表副行)。
  String get scheduleLabel => switch (scheduleKind) {
        'cron' => 'Cron:$scheduleExpr',
        'interval' => '每 ${_intervalHuman(scheduleExpr)}',
        'once' => '一次性',
        _ => scheduleExpr,
      };

  /// 后端把 interval 归一化成纯秒("30m"→"1800"),展示时转回人话。
  static String _intervalHuman(String expr) {
    final secs = int.tryParse(expr);
    if (secs == null || secs <= 0) return expr; // "30m" 等带单位形式原样
    if (secs % 86400 == 0) return '${secs ~/ 86400} 天';
    if (secs % 3600 == 0) return '${secs ~/ 3600} 小时';
    if (secs % 60 == 0) return '${secs ~/ 60} 分钟';
    return '$secs 秒';
  }
}
