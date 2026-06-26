import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/theme/app_theme.dart';
import '../sessions/sessions_controller.dart';
import '../settings/platform_repository.dart';

/// 底部模型选择器:列平台模型,当前会话模型高亮,vision 模型标注。
/// 选中 → PATCH session.model → 就地更新会话列表。
Future<void> showModelPicker(
    BuildContext context, WidgetRef ref, String sessionId) {
  return showModalBottomSheet(
    context: context,
    shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
    builder: (_) => Consumer(builder: (ctx, r, _) {
      final models = r.watch(platformModelsProvider);
      final sessions = r.watch(sessionsControllerProvider).asData?.value ?? [];
      final match = sessions.where((s) => s.id == sessionId);
      final current = match.isEmpty ? null : match.first.model;
      return SafeArea(
        child: models.when(
          loading: () => const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: CircularProgressIndicator())),
          error: (e, _) => Padding(
              padding: const EdgeInsets.all(24),
              child: Text('加载模型失败: $e')),
          data: (pm) => Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(20, 18, 20, 10),
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: Text('选择模型',
                      style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                          color: AppTheme.ink)),
                ),
              ),
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
                  children: [
                    for (final m in pm.models)
                      _modelItem(
                        m: m,
                        selected: m == current,
                        vision: pm.visionModels.contains(m),
                        onTap: () async {
                          Navigator.pop(ctx);
                          await r
                              .read(sessionsControllerProvider.notifier)
                              .patchModel(sessionId, m);
                        },
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
    }),
  );
}

Widget _modelItem({
  required String m,
  required bool selected,
  required bool vision,
  required VoidCallback onTap,
}) =>
    Container(
      margin: const EdgeInsets.only(bottom: 6),
      decoration: BoxDecoration(
        color: selected ? AppTheme.tealSoft : AppTheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: selected ? AppTheme.teal : AppTheme.border),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            child: Row(children: [
              Expanded(
                child: Text(m,
                    style: TextStyle(
                        fontSize: 14.5,
                        fontWeight:
                            selected ? FontWeight.w600 : FontWeight.w500,
                        color: AppTheme.ink)),
              ),
              if (vision) ...[
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                  decoration: BoxDecoration(
                    color: AppTheme.tealSoft,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: const Row(mainAxisSize: MainAxisSize.min, children: [
                    Icon(Icons.image_outlined,
                        size: 12, color: AppTheme.tealDark),
                    SizedBox(width: 3),
                    Text('图片',
                        style:
                            TextStyle(fontSize: 11, color: AppTheme.tealDark)),
                  ]),
                ),
                const SizedBox(width: 8),
              ],
              Icon(selected ? Icons.check_circle : Icons.circle_outlined,
                  size: 20, color: selected ? AppTheme.teal : AppTheme.faint),
            ]),
          ),
        ),
      ),
    );
