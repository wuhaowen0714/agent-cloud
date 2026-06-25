import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../sessions/sessions_controller.dart';
import '../settings/platform_repository.dart';

/// 底部模型选择器:列平台模型,当前会话模型高亮,vision 模型标注"支持图片"。
/// 选中 → PATCH session.model → 就地更新会话列表。
Future<void> showModelPicker(
    BuildContext context, WidgetRef ref, String sessionId) {
  return showModalBottomSheet(
    context: context,
    builder: (_) => Consumer(builder: (ctx, r, _) {
      final models = r.watch(platformModelsProvider);
      final sessions = r.watch(sessionsControllerProvider).asData?.value ?? [];
      final match = sessions.where((s) => s.id == sessionId);
      final current = match.isEmpty ? null : match.first.model;
      return SafeArea(
        child: models.when(
          loading: () => const Padding(
              padding: EdgeInsets.all(24),
              child: Center(child: CircularProgressIndicator())),
          error: (e, _) => Padding(
              padding: const EdgeInsets.all(24), child: Text('加载模型失败: $e')),
          data: (pm) => ListView(
            shrinkWrap: true,
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 16, 16, 8),
                child: Text('选择模型',
                    style:
                        TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
              ),
              for (final m in pm.models)
                ListTile(
                  title: Text(m),
                  subtitle: pm.visionModels.contains(m)
                      ? const Text('支持图片',
                          style: TextStyle(fontSize: 12, color: Colors.teal))
                      : null,
                  trailing: m == current
                      ? const Icon(Icons.check, color: Colors.teal)
                      : null,
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
      );
    }),
  );
}
