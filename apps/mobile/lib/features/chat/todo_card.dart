import 'package:flutter/material.dart';
import '../../core/theme/app_theme.dart';

/// 任务清单(计划模式)条目 + 解析 + 卡片(对标 web TodoCard)。
/// 清单本体在 todo 工具调用的 arguments 里;TurnBlocks 按「首现位置 + 本组最新一次内容」
/// 原位刷新渲染(agent 每次全量重写,不逐卡罗列演进过程)。
enum TodoStatus { pending, inProgress, completed }

typedef TodoItem = ({String content, TodoStatus status});

/// tool_call arguments → items(不可信模型输出,逐项容错;非法项丢弃)。
List<TodoItem> parseTodoItems(Map<String, dynamic> args) {
  final raw = args['items'];
  if (raw is! List) return const [];
  final out = <TodoItem>[];
  for (final it in raw) {
    if (it is! Map) continue;
    final content = it['content'];
    final status = switch (it['status']) {
      'pending' => TodoStatus.pending,
      'in_progress' => TodoStatus.inProgress,
      'completed' => TodoStatus.completed,
      _ => null,
    };
    if (content is! String || content.trim().isEmpty || status == null) continue;
    out.add((content: content.trim(), status: status));
  }
  return out;
}

class TodoCard extends StatelessWidget {
  final List<TodoItem> items;
  const TodoCard(this.items, {super.key});

  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) return const SizedBox.shrink();
    final done = items.where((i) => i.status == TodoStatus.completed).length;
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 12),
      decoration: BoxDecoration(
        color: AppTheme.tealSoft,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.teal.withValues(alpha: 0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            const Text('任务清单',
                style: TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.tealDark)),
            const SizedBox(width: 8),
            Text('$done/${items.length}',
                style:
                    const TextStyle(fontSize: 12, color: AppTheme.teal)),
          ]),
          const SizedBox(height: 6),
          for (final it in items)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                _mark(it.status),
                const SizedBox(width: 7),
                Expanded(
                  child: Text(
                    it.content,
                    style: switch (it.status) {
                      TodoStatus.completed => const TextStyle(
                          fontSize: 14,
                          color: AppTheme.faint,
                          decoration: TextDecoration.lineThrough),
                      TodoStatus.inProgress => const TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: AppTheme.ink),
                      TodoStatus.pending => const TextStyle(
                          fontSize: 14, color: AppTheme.muted),
                    },
                  ),
                ),
              ]),
            ),
        ],
      ),
    );
  }

  Widget _mark(TodoStatus s) => switch (s) {
        TodoStatus.completed =>
          const Icon(Icons.check_circle, size: 16, color: AppTheme.teal),
        TodoStatus.inProgress => const SizedBox(
            width: 16,
            height: 16,
            child: Padding(
              padding: EdgeInsets.all(1.5),
              child: CircularProgressIndicator(
                  strokeWidth: 2, color: AppTheme.teal),
            ),
          ),
        TodoStatus.pending => const Icon(Icons.radio_button_unchecked,
            size: 16, color: AppTheme.faint),
      };
}
