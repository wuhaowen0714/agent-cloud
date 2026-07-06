import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_theme.dart';
import '../../models/scheduled_task.dart';
import '../sessions/sessions_controller.dart';
import 'watch_repository.dart';

/// 值守中心:AI 在你不在时替你干活的任务面板 —— 列表(周期/下次运行/上次状态/开关)、
/// 立即运行、产出时间线(该任务历次运行生成的会话)、新建(每天定时/间隔/自定义 cron)。
/// 结果送达:任务完成 → 系统推送(2.0.0 推送通道)→ 点通知直达产出会话。
class WatchCenterPage extends ConsumerWidget {
  const WatchCenterPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tasks = ref.watch(watchTasksProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('值守中心')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _showCreate(context, ref),
        icon: const Icon(Icons.add),
        label: const Text('新建值守'),
      ),
      body: tasks.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('加载失败: $e')),
        data: (list) {
          if (list.isEmpty) return _empty();
          return RefreshIndicator(
            onRefresh: () => ref.refresh(watchTasksProvider.future),
            child: ListView.builder(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 88),
              itemCount: list.length,
              itemBuilder: (_, i) => _TaskCard(list[i]),
            ),
          );
        },
      ),
    );
  }

  Widget _empty() => Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: const [
          Icon(Icons.radar, size: 44, color: AppTheme.faint),
          SizedBox(height: 10),
          Text('还没有值守任务',
              style: TextStyle(fontSize: 15, color: AppTheme.muted)),
          SizedBox(height: 4),
          Text('让 AI 定期替你盯事情:晨报、提醒、周期检查…\n完成后推送到手机通知',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12.5, color: AppTheme.faint)),
        ]),
      );

  static Future<void> _showCreate(BuildContext context, WidgetRef ref) =>
      showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true, // 键盘顶起
        backgroundColor: Colors.white,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        ),
        builder: (_) => const _CreateSheet(),
      );
}

class _TaskCard extends ConsumerWidget {
  final ScheduledTask t;
  const _TaskCard(this.t);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(AppTheme.rCard),
        border: Border.all(color: AppTheme.border),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(AppTheme.rCard),
          onTap: () => _showDetail(context, ref),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(14, 10, 8, 10),
            child: Row(children: [
              _statusIcon(),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(t.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w600,
                            color: AppTheme.ink)),
                    const SizedBox(height: 3),
                    Text(
                      '${t.scheduleLabel}${_nextRun()}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                          fontSize: 12, color: AppTheme.muted),
                    ),
                  ],
                ),
              ),
              Switch(
                value: t.enabled,
                onChanged: (v) async {
                  try {
                    await ref.read(watchRepoProvider).setEnabled(t.id, v);
                  } finally {
                    ref.invalidate(watchTasksProvider);
                  }
                },
              ),
            ]),
          ),
        ),
      ),
    );
  }

  Widget _statusIcon() => switch (t.lastStatus) {
        'ok' => const Icon(Icons.check_circle, size: 20, color: AppTheme.teal),
        'error' =>
          const Icon(Icons.error_outline, size: 20, color: AppTheme.danger),
        'skipped' =>
          const Icon(Icons.remove_circle_outline, size: 20, color: AppTheme.faint),
        _ => const Icon(Icons.schedule, size: 20, color: AppTheme.faint),
      };

  String _nextRun() {
    final n = t.nextRunAt;
    if (!t.enabled) return ' · 已暂停';
    if (n == null) return '';
    final d = n.difference(DateTime.now());
    if (d.isNegative) return ' · 即将运行';
    if (d.inMinutes < 60) return ' · ${d.inMinutes + 1} 分钟后';
    if (d.inHours < 24) return ' · ${d.inHours} 小时后';
    return ' · ${d.inDays} 天后';
  }

  void _showDetail(BuildContext context, WidgetRef ref) {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (sheetCtx) {
        // 产出时间线:该任务历次运行生成的会话(sessions.scheduled_task_id 关联)
        final sessions = ref
                .read(sessionsControllerProvider)
                .asData
                ?.value
                .where((s) => s.scheduledTaskId == t.id)
                .toList() ??
            [];
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 10),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(t.name,
                    style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: AppTheme.ink)),
                const SizedBox(height: 6),
                Text(t.prompt,
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                    style:
                        const TextStyle(fontSize: 13, color: AppTheme.muted)),
                if (t.lastStatus == 'error' && t.lastError != null) ...[
                  const SizedBox(height: 6),
                  Text('上次出错:${t.lastError}',
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                          fontSize: 12, color: AppTheme.danger)),
                ],
                const SizedBox(height: 10),
                Row(children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      icon: const Icon(Icons.play_arrow, size: 18),
                      label: const Text('立即运行'),
                      onPressed: () async {
                        Navigator.pop(sheetCtx);
                        try {
                          await ref.read(watchRepoProvider).runNow(t.id);
                          ref.invalidate(watchTasksProvider);
                          if (context.mounted) {
                            ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(
                                    content:
                                        Text('已触发运行,完成后会推送通知')));
                          }
                        } catch (_) {
                          if (context.mounted) {
                            ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(content: Text('触发失败,请重试')));
                          }
                        }
                      },
                    ),
                  ),
                  const SizedBox(width: 10),
                  OutlinedButton.icon(
                    icon: const Icon(Icons.delete_outline,
                        size: 18, color: AppTheme.danger),
                    label: const Text('删除',
                        style: TextStyle(color: AppTheme.danger)),
                    onPressed: () async {
                      final ok = await showDialog<bool>(
                        context: sheetCtx,
                        builder: (c) => AlertDialog(
                          title: const Text('删除值守任务'),
                          content: Text('确定删除「${t.name}」?历史产出会话保留。'),
                          actions: [
                            TextButton(
                                onPressed: () => Navigator.pop(c, false),
                                child: const Text('取消')),
                            TextButton(
                                onPressed: () => Navigator.pop(c, true),
                                child: const Text('删除',
                                    style:
                                        TextStyle(color: AppTheme.danger))),
                          ],
                        ),
                      );
                      if (ok != true) return;
                      if (sheetCtx.mounted) Navigator.pop(sheetCtx);
                      try {
                        await ref.read(watchRepoProvider).delete(t.id);
                      } finally {
                        ref.invalidate(watchTasksProvider);
                      }
                    },
                  ),
                ]),
                const SizedBox(height: 12),
                Text('产出记录(${sessions.length})',
                    style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.ink)),
                const SizedBox(height: 4),
                if (sessions.isEmpty)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 8),
                    child: Text('还没有产出,运行后每次结果都会生成一个会话',
                        style:
                            TextStyle(fontSize: 12.5, color: AppTheme.faint)),
                  )
                else
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxHeight: 260),
                    child: ListView(
                      shrinkWrap: true,
                      children: [
                        for (final s in sessions.take(20))
                          ListTile(
                            dense: true,
                            contentPadding: EdgeInsets.zero,
                            leading: Icon(
                                s.unread
                                    ? Icons.mark_email_unread_outlined
                                    : Icons.description_outlined,
                                size: 18,
                                color:
                                    s.unread ? AppTheme.teal : AppTheme.faint),
                            title: Text(s.displayTitle,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(fontSize: 13.5)),
                            trailing: Text(s.relativeTime,
                                style: const TextStyle(
                                    fontSize: 11, color: AppTheme.faint)),
                            onTap: () {
                              Navigator.pop(sheetCtx);
                              context.push('/chat/${s.id}');
                            },
                          ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// 新建值守表单:名称 + 提示词 + 周期(每天定时 / 间隔 / 自定义 cron)。
class _CreateSheet extends ConsumerStatefulWidget {
  const _CreateSheet();
  @override
  ConsumerState<_CreateSheet> createState() => _CreateSheetState();
}

class _CreateSheetState extends ConsumerState<_CreateSheet> {
  final _name = TextEditingController();
  final _prompt = TextEditingController();
  final _cron = TextEditingController(text: '0 8 * * *');
  String _mode = 'daily'; // daily | interval | cron
  TimeOfDay _dailyAt = const TimeOfDay(hour: 8, minute: 0);
  String _interval = '1h';
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    _prompt.dispose();
    _cron.dispose();
    super.dispose();
  }

  (String, String) _schedule() => switch (_mode) {
        'daily' => ('cron', '${_dailyAt.minute} ${_dailyAt.hour} * * *'),
        'interval' => ('interval', _interval),
        _ => ('cron', _cron.text.trim()),
      };

  Future<void> _create() async {
    final name = _name.text.trim();
    final prompt = _prompt.text.trim();
    if (name.isEmpty || prompt.isEmpty || _busy) return;
    final agents = ref.read(agentsProvider).asData?.value ?? [];
    if (agents.isEmpty) return;
    setState(() => _busy = true);
    final (kind, expr) = _schedule();
    try {
      await ref.read(watchRepoProvider).create(
            name: name,
            prompt: prompt,
            agentConfigId: agents.first.id,
            scheduleKind: kind,
            scheduleExpr: expr,
          );
      ref.invalidate(watchTasksProvider);
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) {
        setState(() => _busy = false);
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('创建失败:$e')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      // 键盘顶起
      padding:
          EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('新建值守任务',
                  style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                      color: AppTheme.ink)),
              const SizedBox(height: 12),
              TextField(
                controller: _name,
                decoration: const InputDecoration(
                    hintText: '任务名(如:AI 新闻晨报)', isDense: true),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _prompt,
                minLines: 2,
                maxLines: 4,
                decoration: const InputDecoration(
                    hintText: '要 AI 做什么(如:搜索今天的 AI 大新闻,整理成 5 条以内的简报)',
                    isDense: true),
              ),
              const SizedBox(height: 12),
              Wrap(spacing: 8, children: [
                _modeChip('daily', '每天定时'),
                _modeChip('interval', '按间隔'),
                _modeChip('cron', '自定义 Cron'),
              ]),
              const SizedBox(height: 10),
              if (_mode == 'daily')
                OutlinedButton.icon(
                  icon: const Icon(Icons.access_time, size: 18),
                  label: Text(
                      '每天 ${_dailyAt.hour.toString().padLeft(2, '0')}:${_dailyAt.minute.toString().padLeft(2, '0')}'),
                  onPressed: () async {
                    final t = await showTimePicker(
                        context: context, initialTime: _dailyAt);
                    if (t != null) setState(() => _dailyAt = t);
                  },
                )
              else if (_mode == 'interval')
                Wrap(spacing: 8, children: [
                  for (final it in ['30m', '1h', '6h', '12h', '1d'])
                    ChoiceChip(
                      label: Text('每 $it'),
                      selected: _interval == it,
                      onSelected: (_) => setState(() => _interval = it),
                    ),
                ])
              else
                TextField(
                  controller: _cron,
                  decoration: const InputDecoration(
                      hintText: '如 0 9 * * 1(每周一 9 点)', isDense: true),
                ),
              const SizedBox(height: 14),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: _busy ? null : _create,
                  child: Text(_busy ? '创建中…' : '创建'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _modeChip(String v, String label) => ChoiceChip(
        label: Text(label),
        selected: _mode == v,
        onSelected: (_) => setState(() => _mode = v),
      );
}
