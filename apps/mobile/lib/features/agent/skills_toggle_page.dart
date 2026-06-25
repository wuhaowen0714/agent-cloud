import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/theme/app_theme.dart';
import '../../models/skill.dart';
import '../settings/skills_page.dart'; // skillsProvider(全部技能)
import 'agent_repository.dart';

/// 技能开关(per-agent):全部技能,切换即全量替换该 agent 启用集。
class SkillsTogglePage extends ConsumerWidget {
  final String agentId;
  const SkillsTogglePage(this.agentId, {super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final pool = ref.watch(skillsProvider);
    final enabled = ref.watch(agentSkillsProvider(agentId));
    return Scaffold(
      appBar: AppBar(title: const Text('技能')),
      body: pool.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('加载失败: $e')),
        data: (list) {
          if (list.isEmpty) {
            return const Center(
                child: Text('还没有安装技能',
                    style: TextStyle(color: AppTheme.muted)));
          }
          final ids = (enabled.asData?.value ?? const <Skill>[])
              .map((s) => s.id)
              .toSet();
          return ListView(
            padding: const EdgeInsets.all(12),
            children: [for (final s in list) _tile(ref, s, ids)],
          );
        },
      ),
    );
  }

  Widget _tile(WidgetRef ref, Skill s, Set<String> enabledIds) {
    final on = enabledIds.contains(s.id);
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
              Text(s.name,
                  style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: AppTheme.ink)),
              if (s.description.isNotEmpty) ...[
                const SizedBox(height: 2),
                Text(s.description,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style:
                        const TextStyle(fontSize: 12, color: AppTheme.muted)),
              ],
            ],
          ),
        ),
        Switch(
          value: on,
          onChanged: (v) {
            final next = {...enabledIds};
            if (v) {
              next.add(s.id);
            } else {
              next.remove(s.id);
            }
            ref
                .read(agentRepoProvider)
                .setAgentSkills(agentId, next.toList())
                .then((_) => ref.invalidate(agentSkillsProvider(agentId)));
          },
        ),
      ]),
    );
  }
}
