import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/theme/app_theme.dart';
import '../sessions/sessions_controller.dart'; // agentsProvider
import 'agent_repository.dart';
import 'agent_tools.dart';

/// 工具开关(per-agent):enabled_tools 即点即存,至少保留一个。
class ToolsPage extends ConsumerWidget {
  final String agentId;
  const ToolsPage(this.agentId, {super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final agents = ref.watch(agentsProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('工具')),
      body: agents.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('加载失败: $e')),
        data: (list) {
          final m = list.where((a) => a.id == agentId);
          if (m.isEmpty) return const Center(child: Text('未找到智能体'));
          final checked = enabledToChecked(m.first.enabledTools);
          return ListView(
            padding: const EdgeInsets.all(12),
            children: [for (final t in kBuiltinTools) _tile(ref, t, checked)],
          );
        },
      ),
    );
  }

  Widget _tile(WidgetRef ref, ToolInfo t, Set<String> checked) {
    final on = checked.contains(t.name);
    final lastOn = on && checked.length == 1; // 至少保留一个 → 锁定
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.fromLTRB(14, 6, 8, 6),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(AppTheme.rField),
        border: Border.all(color: AppTheme.border),
      ),
      child: Row(children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(t.name,
                  style: const TextStyle(
                      fontFamily: 'monospace',
                      fontSize: 13.5,
                      fontWeight: FontWeight.w600,
                      color: AppTheme.ink)),
              const SizedBox(height: 2),
              Text(t.desc,
                  style: const TextStyle(fontSize: 12, color: AppTheme.muted)),
            ],
          ),
        ),
        Switch(
          value: on,
          onChanged: lastOn
              ? null
              : (v) {
                  final next = {...checked};
                  if (v) {
                    next.add(t.name);
                  } else {
                    next.remove(t.name);
                  }
                  if (next.isEmpty) return;
                  ref
                      .read(agentRepoProvider)
                      .patchTools(agentId, checkedToEnabled(next))
                      .then((_) => ref.invalidate(agentsProvider));
                },
        ),
      ]),
    );
  }
}
