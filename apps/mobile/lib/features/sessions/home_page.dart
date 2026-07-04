import 'dart:async'; // unawaited
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../core/theme/app_theme.dart';
import '../../core/util/time_group.dart';
import '../../models/agent_config.dart';
import '../../models/session.dart';
import '../update/update_service.dart';
import '../chat/upload_compose.dart'; // parseUserMessage(预览剥 marker)
import 'sessions_controller.dart';

// 选中 agent 后,该 agent 的会话按天分组的列表项
sealed class _Item {
  const _Item();
}

class _DateHeader extends _Item {
  final String label;
  final bool expanded;
  final int count;
  const _DateHeader(this.label, this.expanded, this.count);
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
  final _search = TextEditingController(); // 会话标题搜索(纯前端过滤)
  String? _selectedAgentId;
  final Set<String> _toggledDates = {}; // 手动 toggle 的天分组(今天默认开,其它默认折叠)

  bool _dateExpanded(String label) {
    final t = _toggledDates.contains(label);
    return label == '今天' ? !t : t;
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) checkUpdate(context, ref, silent: true);
    });
  }

  void _toast(String m) {
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));
    }
  }

  Future<void> _newSession(String? agentId) async {
    if (agentId == null) {
      _toast('没有可用的智能体');
      return;
    }
    try {
      final s =
          await ref.read(sessionsControllerProvider.notifier).create(agentId);
      if (mounted) context.push('/chat/${s.id}');
    } catch (e) {
      _toast('创建会话失败: $e');
    }
  }

  Future<void> _deleteAgent(AgentConfig a) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('删除「${a.name}」?'),
        content: const Text('将连同该智能体的全部会话一起删除,不可恢复。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('取消')),
          TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('删除',
                  style: TextStyle(color: AppTheme.danger))),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(sessionsControllerProvider.notifier).deleteAgent(a.id);
      if (mounted && _selectedAgentId == a.id) {
        setState(() => _selectedAgentId = null); // 回退到默认(第一个)
      }
    } catch (e) {
      final busy = e is DioException && e.response?.statusCode == 409;
      _toast(busy ? '「${a.name}」有会话在运行,无法删除' : '删除失败: $e');
    }
  }

  void _agentActions(AgentConfig a) {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
            leading: const Icon(Icons.settings_outlined),
            title: const Text('设置'),
            onTap: () {
              Navigator.pop(context);
              context.push('/agent/${a.id}/settings');
            },
          ),
          ListTile(
            leading: const Icon(Icons.delete_outline, color: AppTheme.danger),
            title:
                const Text('删除', style: TextStyle(color: AppTheme.danger)),
            onTap: () {
              Navigator.pop(context);
              _deleteAgent(a);
            },
          ),
          const SizedBox(height: 8),
        ]),
      ),
    );
  }

  Future<void> _createAgent() async {
    final ctrl = TextEditingController();
    final name = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('新建智能体'),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          decoration: const InputDecoration(hintText: '智能体名称'),
          onSubmitted: (v) => Navigator.pop(ctx, v.trim()),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, ctrl.text.trim()),
              child: const Text('创建')),
        ],
      ),
    );
    ctrl.dispose();
    if (name == null || name.isEmpty) return;
    try {
      final a = await ref
          .read(sessionsControllerProvider.notifier)
          .createAgent(name);
      if (mounted) {
        setState(() => _selectedAgentId = a.id);
        context.push('/agent/${a.id}/settings');
      }
    } catch (e) {
      _toast('创建失败: $e');
    }
  }

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

  List<_Item> _buildDateItems(List<Session> ss) {
    final epoch = DateTime.fromMillisecondsSinceEpoch(0);
    final sorted = [...ss]
      ..sort((a, b) =>
          (b.lastActiveAt ?? epoch).compareTo(a.lastActiveAt ?? epoch));
    final byLabel = <String, List<Session>>{};
    for (final s in sorted) {
      (byLabel[timeGroupLabel(s.lastActiveAt)] ??= []).add(s);
    }
    final items = <_Item>[];
    for (final e in byLabel.entries) {
      final open = _dateExpanded(e.key);
      items.add(_DateHeader(e.key, open, e.value.length));
      if (open) {
        for (final s in e.value) {
          items.add(_SessionItem(s));
        }
      }
    }
    return items;
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final agents = ref.watch(agentsProvider).asData?.value ?? const [];
    final sessionsAsync = ref.watch(sessionsControllerProvider);
    final sessions = sessionsAsync.asData?.value ?? const [];
    // 选中 agent:默认第一个;选中的被删了则回退第一个
    var selectedId = _selectedAgentId;
    if (selectedId == null || !agents.any((a) => a.id == selectedId)) {
      selectedId = agents.isNotEmpty ? agents.first.id : null;
    }
    final countByAgent = <String, int>{};
    for (final s in sessions) {
      countByAgent.update(s.agentConfigId, (v) => v + 1, ifAbsent: () => 1);
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('会话'),
        actions: [
          IconButton(
              icon: const Icon(Icons.folder_outlined),
              tooltip: '文件',
              onPressed: () => context.push('/files')),
          IconButton(
              icon: const Icon(Icons.terminal),
              tooltip: '终端',
              onPressed: () => context.push('/terminal')),
          IconButton(
              icon: const Icon(Icons.settings_outlined),
              tooltip: '设置',
              onPressed: () => context.push('/settings')),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _newSession(selectedId),
        icon: const Icon(Icons.add),
        label: const Text('新对话'),
      ),
      body: Column(children: [
        if (agents.isNotEmpty) _agentBar(agents, selectedId, countByAgent),
        const Divider(height: 1),
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
          child: TextField(
            controller: _search,
            onChanged: (_) => setState(() {}),
            decoration: InputDecoration(
              hintText: '搜索会话…',
              prefixIcon: const Icon(Icons.search, size: 18),
              suffixIcon: _search.text.isEmpty
                  ? null
                  : IconButton(
                      icon: const Icon(Icons.clear, size: 16),
                      onPressed: () => setState(_search.clear),
                    ),
              isDense: true,
              contentPadding:
                  const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            ),
          ),
        ),
        Expanded(child: _sessionArea(sessionsAsync, selectedId)),
      ]),
    );
  }

  Widget _agentBar(
      List<AgentConfig> agents, String? selectedId, Map<String, int> counts) {
    return SizedBox(
      height: 52,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
        itemCount: agents.length + 1,
        separatorBuilder: (_, _) => const SizedBox(width: 8),
        itemBuilder: (_, i) {
          if (i == agents.length) {
            return GestureDetector(
              onTap: _createAgent,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 14),
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: AppTheme.surface,
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(color: AppTheme.border),
                ),
                child: const Icon(Icons.add, size: 18, color: AppTheme.muted),
              ),
            );
          }
          final a = agents[i];
          final sel = a.id == selectedId;
          final c = counts[a.id] ?? 0;
          return GestureDetector(
            onTap: () => setState(() => _selectedAgentId = a.id),
            onLongPress: () => _agentActions(a),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 14),
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: sel ? AppTheme.teal : AppTheme.surface,
                borderRadius: BorderRadius.circular(20),
                border: Border.all(color: sel ? AppTheme.teal : AppTheme.border),
              ),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(Icons.smart_toy_outlined,
                    size: 15, color: sel ? Colors.white : AppTheme.muted),
                const SizedBox(width: 5),
                Text(a.name,
                    style: TextStyle(
                        fontSize: 13.5,
                        fontWeight: FontWeight.w600,
                        color: sel ? Colors.white : AppTheme.ink)),
                if (c > 0) ...[
                  const SizedBox(width: 6),
                  // 会话数徽章:小圆底与名字区隔,避免「Agent 8 2」连读歧义
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                    decoration: BoxDecoration(
                      color: sel
                          ? Colors.white.withValues(alpha: 0.25)
                          : AppTheme.borderSoft,
                      borderRadius: BorderRadius.circular(9),
                    ),
                    child: Text('$c',
                        style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                            color: sel ? Colors.white : AppTheme.muted)),
                  ),
                ],
              ]),
            ),
          );
        },
      ),
    );
  }

  Widget _sessionArea(AsyncValue<List<Session>> async, String? selectedId) {
    return async.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text('加载失败: $e')),
      data: (all) {
        if (selectedId == null) {
          return _empty('还没有智能体', '点右上角 + 新建一个开始');
        }
        var mine =
            all.where((s) => s.agentConfigId == selectedId).toList();
        final q = _search.text.trim().toLowerCase();
        if (q.isNotEmpty) {
          mine = mine
              .where((s) => s.displayTitle.toLowerCase().contains(q))
              .toList();
          if (mine.isEmpty) return _empty('无匹配会话', '换个关键词试试');
        }
        if (mine.isEmpty) {
          return _empty('还没有会话', '点右下角「新对话」开始');
        }
        final items = _buildDateItems(mine);
        return RefreshIndicator(
          onRefresh: () =>
              ref.read(sessionsControllerProvider.notifier).refresh(),
          child: ListView.builder(
            padding: const EdgeInsets.fromLTRB(12, 4, 12, 88),
            itemCount: items.length,
            itemBuilder: (_, i) {
              final item = items[i];
              return switch (item) {
                _DateHeader() => _dateHeader(item),
                _SessionItem(:final session) => _sessionCard(session),
              };
            },
          ),
        );
      },
    );
  }

  Widget _dateHeader(_DateHeader h) => Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(8),
          onTap: () => setState(() => _toggledDates.contains(h.label)
              ? _toggledDates.remove(h.label)
              : _toggledDates.add(h.label)),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(4, 12, 4, 6),
            child: Row(children: [
              Icon(h.expanded ? Icons.expand_more : Icons.chevron_right,
                  size: 16, color: AppTheme.muted),
              const SizedBox(width: 3),
              Text(h.label,
                  style: const TextStyle(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w600,
                      color: AppTheme.muted)),
              const SizedBox(width: 6),
              Text('${h.count}',
                  style: const TextStyle(fontSize: 12, color: AppTheme.faint)),
            ]),
          ),
        ),
      );

  Widget _empty(String title, String hint) => Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Container(
            width: 64,
            height: 64,
            decoration: const BoxDecoration(
                color: AppTheme.tealSoft, shape: BoxShape.circle),
            child: const Icon(Icons.forum_outlined,
                size: 30, color: AppTheme.teal),
          ),
          const SizedBox(height: 14),
          Text(title,
              style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.ink)),
          const SizedBox(height: 6),
          Text(hint, style: const TextStyle(color: AppTheme.muted)),
        ]),
      );

  // 紧凑会话卡:无大图标,标题 + 时间在一行,模型在副行。
  /// 列表副行预览:最后一条消息文本(剥附件/技能 marker,压掉换行);无消息回退模型名。
  String _preview(Session s) {
    final raw = s.lastMessage;
    if (raw == null || raw.trim().isEmpty) return s.model;
    final body = parseUserMessage(raw).body.replaceAll(RegExp(r'\s+'), ' ').trim();
    return body.isEmpty ? s.model : body;
  }

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
              onTap: () {
                if (s.unread) {
                  // 进会话即消未读点(对齐 web);best-effort,失败下次点击再试
                  unawaited(ref
                      .read(sessionsRepoProvider)
                      .markRead(s.id)
                      .then((_) => ref
                          .read(sessionsControllerProvider.notifier)
                          .refresh())
                      .catchError((_) {}));
                }
                context.push('/chat/${s.id}');
              },
              onLongPress: () => _showActions(s),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(14, 9, 12, 9),
                child: Row(children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(children: [
                          if (s.unread) ...[
                            // 未读点(定时任务有新回复):teal 实心小圆
                            Container(
                                width: 7,
                                height: 7,
                                decoration: const BoxDecoration(
                                    color: AppTheme.teal,
                                    shape: BoxShape.circle)),
                            const SizedBox(width: 6),
                          ],
                          Expanded(
                            child: Text(s.displayTitle,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(
                                    fontSize: 15,
                                    fontWeight: FontWeight.w600,
                                    color: s.unread
                                        ? AppTheme.tealDark
                                        : AppTheme.ink)),
                          ),
                          if (s.relativeTime.isNotEmpty)
                            Text(s.relativeTime,
                                style: const TextStyle(
                                    fontSize: 11.5, color: AppTheme.faint)),
                        ]),
                        const SizedBox(height: 3),
                        // 副行:最后一条消息预览(剥附件/技能 marker);无消息回退模型名
                        Text(
                          _preview(s),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              fontSize: 12.5, color: AppTheme.muted),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 8),
                  const Icon(Icons.chevron_right,
                      size: 20, color: AppTheme.faint),
                ]),
              ),
            ),
          ),
        ),
      );
}
