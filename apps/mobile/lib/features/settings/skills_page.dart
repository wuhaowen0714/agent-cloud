import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/theme/app_theme.dart';
import '../../models/skill.dart';
import 'settings_repository.dart';

final skillsProvider = FutureProvider.autoDispose<List<Skill>>(
    (ref) => ref.read(settingsRepoProvider).listSkills());

class SkillsPage extends ConsumerWidget {
  const SkillsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final skills = ref.watch(skillsProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('技能')),
      body: skills.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('加载失败: $e')),
        data: (list) => list.isEmpty
            ? const Center(
                child: Text('还没有安装技能',
                    style: TextStyle(color: AppTheme.muted)))
            : ListView.builder(
                padding: const EdgeInsets.all(12),
                itemCount: list.length,
                itemBuilder: (_, i) => _tile(context, ref, list[i]),
              ),
      ),
    );
  }

  Widget _tile(BuildContext context, WidgetRef ref, Skill s) => Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: AppTheme.surface,
          borderRadius: BorderRadius.circular(AppTheme.rCard),
          border: Border.all(color: AppTheme.border),
        ),
        child: Row(children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
                color: AppTheme.tealSoft,
                borderRadius: BorderRadius.circular(10)),
            child: const Icon(Icons.extension_outlined,
                color: AppTheme.teal, size: 20),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  Flexible(
                    child: Text(s.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            fontWeight: FontWeight.w600,
                            fontSize: 14.5,
                            color: AppTheme.ink)),
                  ),
                  if (s.version.isNotEmpty) ...[
                    const SizedBox(width: 6),
                    Text('v${s.version}',
                        style: const TextStyle(
                            fontSize: 11, color: AppTheme.faint)),
                  ],
                ]),
                if (s.description.isNotEmpty) ...[
                  const SizedBox(height: 3),
                  Text(s.description,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                          fontSize: 12.5, color: AppTheme.muted, height: 1.3)),
                ],
              ],
            ),
          ),
          if (s.source != 'builtin') // 内置技能不可删
            IconButton(
              icon: const Icon(Icons.delete_outline,
                  size: 20, color: AppTheme.faint),
              onPressed: () async {
                await ref.read(settingsRepoProvider).deleteSkill(s.id);
                ref.invalidate(skillsProvider);
              },
            ),
        ]),
      );
}
