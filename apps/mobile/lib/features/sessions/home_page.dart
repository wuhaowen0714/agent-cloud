import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
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
            builder: (_) => SafeArea(
              child: ListView(
                shrinkWrap: true,
                children: agents
                    .map((a) => ListTile(
                          title: Text(a.name),
                          onTap: () => Navigator.pop(context, a.id),
                        ))
                    .toList(),
              ),
            ),
          );
    if (agentId != null) {
      await ref.read(sessionsControllerProvider.notifier).create(agentId);
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
      floatingActionButton: FloatingActionButton(
        onPressed: _newSession,
        child: const Icon(Icons.add),
      ),
      body: sessions.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('加载失败: $e')),
        data: (list) => list.isEmpty
            ? const Center(child: Text('还没有会话,点 + 新建'))
            : RefreshIndicator(
                onRefresh: () =>
                    ref.read(sessionsControllerProvider.notifier).refresh(),
                child: ListView.separated(
                  itemCount: list.length,
                  separatorBuilder: (_, _) => const Divider(height: 1),
                  itemBuilder: (_, i) {
                    final s = list[i];
                    return Dismissible(
                      key: ValueKey(s.id),
                      direction: DismissDirection.endToStart,
                      background: Container(
                        color: Colors.red,
                        alignment: Alignment.centerRight,
                        padding: const EdgeInsets.only(right: 16),
                        child: const Icon(Icons.delete, color: Colors.white),
                      ),
                      onDismissed: (_) => ref
                          .read(sessionsControllerProvider.notifier)
                          .remove(s.id),
                      child: ListTile(
                        title: Text(s.displayTitle),
                        subtitle: Text(s.model),
                        onTap: () => context.go('/chat/${s.id}'),
                      ),
                    );
                  },
                ),
              ),
      ),
    );
  }
}
