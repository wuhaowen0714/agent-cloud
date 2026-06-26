import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../core/theme/app_theme.dart';
import '../../core/util/time_group.dart';
import '../../models/agent_config.dart';
import '../../models/session.dart';
import '../update/update_service.dart';
import 'sessions_controller.dart';

// 列表项:agent 大标题 / 天小标题 / 会话卡
sealed class _Item {
  const _Item();
}

class _AgentHeader extends _Item {
  final String name;
  const _AgentHeader(this.name);
}

class _DateHeader extends _Item {
  final String label;
  const _DateHeader(this.label);
}

class _SessionItem extends _Item {
  final Session session;
  const _SessionItem(this.session);
}

class HomePage extends ConsumerStatefulWidget {
  const HomePage({super.key});
  @override
  ConsumerState<HomePage> createState() => _HomePageState();
}

class _HomePageState extends ConsumerState<HomePage> {
  @override
  void initState() {
    super.initState();
    // 进入主页(已登录)后静默检查更新。
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) checkUpdate(context, ref, silent: true);
    });
  }

  void _toast(String m) {
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));
    }
  }

  Future<void> _newSession() async {
    // 关键:await future 确保 agents 已加载(此前用 .asData 在首次点击时拿到空 → 静默失败)
    List<AgentConfig> agents;
    try {
      agents = await ref.read(agentsProvider.future);
    } catch (e) {
      _toast('加载智能体失败: $e');
      return;
    }
    if (!mounted) return;
    if (agents.isEmpty) {
      _toast('没有可用的智能体');
      return;
    }
    final agentId = agents.length == 1
        ? agents.first.id
        : await showModalBottomSheet<String>(
            context: context,
            shape: const RoundedRectangleBorder(
                borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
            builder: (_) => SafeArea(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Padding(
                    padding: EdgeInsets.fromLTRB(20, 18, 20, 8),
                    child: Align(
                      alignment: Alignment.centerLeft,
                      child: Text('选择智能体',
                          style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w600,
                              color: AppTheme.ink)),
                    ),
                  ),
                  ...agents.map((a) => ListTile(
                        leading: const Icon(Icons.smart_toy_outlined),
                        title: Text(a.name),
                        onTap: () => Navigator.pop(context, a.id),
                      )),
                  const SizedBox(height: 8),
                ],
              ),
            ),
          );
    if (agentId == null) return;
    try {
      final s =
          await ref.read(sessionsControllerProvider.notifier).create(agentId);
      if (mounted) context.go('/chat/${s.id}'); // 建完直接进会话
    } catch (e) {
      _toast('创建会话失败: $e');
    }
  }

  /// 长按会话弹操作菜单:重命名 / 删除。
  void _showActions(Session s) {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
            leading: const Icon(Icons.edit_outlined),
            title: const Text('重命名'),
            onTap: () {
              Navigator.pop(context);
              _rename(s);
            },
          ),
          ListTile(
            leading: const Icon(Icons.delete_outline, color: AppTheme.danger),
            title:
                const Text('删除', style: TextStyle(color: AppTheme.danger)),
            onTap: () {
              Navigator.pop(context);
              ref.read(sessionsControllerProvider.notifier).remove(s.id);
            },
          ),
          const SizedBox(height: 8),
        ]),
      ),
    );
  }

  Future<void> _rename(Session s) async {
    final ctrl = TextEditingController(text: s.title ?? '');
    final title = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('重命名会话'),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          decoration: const InputDecoration(hintText: '会话标题'),
          onSubmitted: (v) => Navigator.pop(ctx, v.trim()),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, ctrl.text.trim()),
              child: const Text('保存')),
        ],
      ),
    );
    ctrl.dispose();
    if (title != null && title.isNotEmpty) {
      await ref.read(sessionsControllerProvider.notifier).rename(s.id, title);
    }
  }

  /// 会话 → 两级分组(agent → 天)的扁平列表。
  List<_Item> _buildItems(List<Session> sessions, Map<String, String> names) {
    final epoch = DateTime.fromMillisecondsSinceEpoch(0);
    final byAgent = <String, List<Session>>{};
    for (final s in sessions) {
      (byAgent[s.agentConfigId] ??= []).add(s);
    }
    DateTime latest(List<Session> ss) => ss
        .map((s) => s.lastActiveAt ?? epoch)
        .reduce((a, b) => a.isAfter(b) ? a : b);
    // agent 组按各自最近活跃降序
    final agentIds = byAgent.keys.toList()
      ..sort((a, b) => latest(byAgent[b]!).compareTo(latest(byAgent[a]!)));

    final items = <_Item>[];
    for (final aid in agentIds) {
      items.add(_AgentHeader(names[aid] ?? '智能体'));
      final ss = byAgent[aid]!
        ..sort((a, b) =>
            (b.lastActiveAt ?? epoch).compareTo(a.lastActiveAt ?? epoch));
      String? cur;
      for (final s in ss) {
        final lbl = timeGroupLabel(s.lastActiveAt);
        if (lbl != cur) {
          items.add(_DateHeader(lbl));
          cur = lbl;
        }
        items.add(_SessionItem(s));
      }
    }
    return items;
  }

  @override
  Widget build(BuildContext context) {
    final sessions = ref.watch(sessionsControllerProvider);
    final agents = ref.watch(agentsProvider).asData?.value ?? [];
    final names = {for (final a in agents) a.id: a.name};
    return Scaffold(
      appBar: AppBar(
        title: const Text('会话'),
        actions: [
          IconButton(
            icon: const Icon(Icons.folder_outlined),
            tooltip: '文件',
            onPressed: () => context.push('/files'),
          ),
          IconButton(
            icon: const Icon(Icons.terminal),
            tooltip: '终端',
            onPressed: () => context.push('/terminal'),
          ),
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            tooltip: '设置',
            onPressed: () => context.push('/settings'),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _newSession,
        icon: const Icon(Icons.add),
        label: const Text('新对话'),
      ),
      body: sessions.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('加载失败: $e')),
        data: (list) {
          if (list.isEmpty) return _emptyState();
          final items = _buildItems(list, names);
          return RefreshIndicator(
            onRefresh: () =>
                ref.read(sessionsControllerProvider.notifier).refresh(),
            child: ListView.builder(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 88),
              itemCount: items.length,
              itemBuilder: (_, i) => switch (items[i]) {
                _AgentHeader(:final name) => _agentHeader(name),
                _DateHeader(:final label) => _dateHeader(label),
                _SessionItem(:final session) => _sessionCard(session),
              },
            ),
          );
        },
      ),
    );
  }

  Widget _agentHeader(String name) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 16, 4, 8),
        child: Row(children: [
          const Icon(Icons.smart_toy_outlined, size: 17, color: AppTheme.teal),
          const SizedBox(width: 6),
          Text(name,
              style: const TextStyle(
                  fontSize: 14.5,
                  fontWeight: FontWeight.w700,
                  color: AppTheme.ink)),
        ]),
      );

  Widget _dateHeader(String label) => Padding(
        padding: const EdgeInsets.fromLTRB(6, 10, 6, 6),
        child: Text(label,
            style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: AppTheme.muted)),
      );

  Widget _emptyState() => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 72,
              height: 72,
              decoration: const BoxDecoration(
                  color: AppTheme.tealSoft, shape: BoxShape.circle),
              child: const Icon(Icons.forum_outlined,
                  size: 34, color: AppTheme.teal),
            ),
            const SizedBox(height: 16),
            const Text('还没有会话',
                style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.ink)),
            const SizedBox(height: 6),
            const Text('点右下角「新对话」开始',
                style: TextStyle(color: AppTheme.muted)),
          ],
        ),
      );

  Widget _sessionCard(Session s) => Dismissible(
        key: ValueKey(s.id),
        direction: DismissDirection.endToStart,
        background: Container(
          margin: const EdgeInsets.only(bottom: 8),
          alignment: Alignment.centerRight,
          padding: const EdgeInsets.only(right: 20),
          decoration: BoxDecoration(
            color: AppTheme.dangerSoft,
            borderRadius: BorderRadius.circular(AppTheme.rCard),
          ),
          child: const Icon(Icons.delete_outline, color: AppTheme.danger),
        ),
        onDismissed: (_) =>
            ref.read(sessionsControllerProvider.notifier).remove(s.id),
        child: Container(
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
              onTap: () => context.go('/chat/${s.id}'),
              onLongPress: () => _showActions(s),
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Row(children: [
                  Container(
                    width: 40,
                    height: 40,
                    decoration: BoxDecoration(
                      color: AppTheme.tealSoft,
                      borderRadius: BorderRadius.circular(11),
                    ),
                    child: const Icon(Icons.forum_outlined,
                        color: AppTheme.teal, size: 20),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(children: [
                          Expanded(
                            child: Text(s.displayTitle,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                    fontSize: 15,
                                    fontWeight: FontWeight.w600,
                                    color: AppTheme.ink)),
                          ),
                          if (s.relativeTime.isNotEmpty)
                            Text(s.relativeTime,
                                style: const TextStyle(
                                    fontSize: 11.5, color: AppTheme.faint)),
                        ]),
                        const SizedBox(height: 4),
                        Row(children: [
                          const Icon(Icons.memory,
                              size: 13, color: AppTheme.faint),
                          const SizedBox(width: 4),
                          Flexible(
                            child: Text(s.model,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                    fontSize: 12.5, color: AppTheme.muted)),
                          ),
                        ]),
                      ],
                    ),
                  ),
                  const Icon(Icons.chevron_right, color: AppTheme.faint),
                ]),
              ),
            ),
          ),
        ),
      );
}
