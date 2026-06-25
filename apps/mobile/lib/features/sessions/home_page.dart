import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../core/theme/app_theme.dart';
import '../../models/session.dart';
import '../update/update_service.dart';
import 'sessions_controller.dart';

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

  Future<void> _newSession() async {
    final agents = ref.read(agentsProvider).asData?.value ?? [];
    if (agents.isEmpty) return;
    // 单 agent 直接建;多 agent 弹底部选择
    final agentId = agents.length == 1
        ? agents.first.id
        : await showModalBottomSheet<String>(
            context: context,
            shape: const RoundedRectangleBorder(
                borderRadius:
                    BorderRadius.vertical(top: Radius.circular(20))),
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
    if (agentId != null) {
      await ref.read(sessionsControllerProvider.notifier).create(agentId);
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

  @override
  Widget build(BuildContext context) {
    final sessions = ref.watch(sessionsControllerProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('会话'),
        actions: [
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
        data: (list) => list.isEmpty
            ? _emptyState()
            : RefreshIndicator(
                onRefresh: () =>
                    ref.read(sessionsControllerProvider.notifier).refresh(),
                child: ListView.builder(
                  padding: const EdgeInsets.fromLTRB(12, 12, 12, 88),
                  itemCount: list.length,
                  itemBuilder: (_, i) => _sessionCard(list[i]),
                ),
              ),
      ),
    );
  }

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
          margin: const EdgeInsets.only(bottom: 10),
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
          margin: const EdgeInsets.only(bottom: 10),
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
                    width: 42,
                    height: 42,
                    decoration: BoxDecoration(
                      color: AppTheme.tealSoft,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: const Icon(Icons.forum_outlined,
                        color: AppTheme.teal, size: 22),
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
