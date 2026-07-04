import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart' show GoRouterHelper; // 只要 context.push(Block 与本地模型撞名)
import 'package:markdown/markdown.dart' as md;
import '../../core/theme/app_theme.dart';
import '../files/files_repository.dart'; // sentImageProvider / fileIndexProvider
import '../../models/block.dart';
import 'edit_diff.dart';
import 'todo_card.dart';
import 'workspace_paths.dart';

// generate_image/edit_image 成功结果文本里嵌着落盘路径(worker 回填 media/picture/..)
final _imgPathRe = RegExp(
    r'''(media/picture/[^\s"']+\.(?:png|jpe?g|webp|gif))''',
    caseSensitive: false);

String? _toolImagePath(ToolBlock b) {
  final r = b.result;
  if ((b.call.name == 'generate_image' || b.call.name == 'edit_image') &&
      r != null &&
      !r.isError) {
    return _imgPathRe.firstMatch(r.content)?.group(1);
  }
  return null;
}

// 子 agent 用 indigo 区分于主 teal(表示"嵌套子任务")
const _indigo = Color(0xFF6366F1);
const _indigoSoft = Color(0xFFEEF2FF);

/// 渲染一组 block(对标 web TurnBlocks):思考/文本/工具卡/子 agent 折叠卡。
class TurnBlocks extends StatelessWidget {
  final List<Block> blocks;
  final void Function(String text)? onApprove; // 危险操作确认:发送含批准码的确认消息
  const TurnBlocks(this.blocks, {super.key, this.onApprove});

  @override
  Widget build(BuildContext context) {
    // 任务清单(todo 工具):agent 每次全量重写清单 → 多次调用只在【首现位置】渲染一张卡,
    // 内容取本组 blocks 里【最新一次】的 items(原位刷新);其余 todo 块跳过。pending 进度卡
    // (参数生成中,args 空)照走普通工具卡。子 agent 卡内部递归时各自成组,天然独立。
    final todos = blocks
        .whereType<ToolBlock>()
        .where((b) => b.call.name == 'todo' && b.progress == null)
        .toList();
    final firstTodoId = todos.isEmpty ? null : todos.first.id;
    final latestItems =
        todos.isEmpty ? const <TodoItem>[] : parseTodoItems(todos.last.call.arguments);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final b in blocks)
          if (b is ToolBlock && b.call.name == 'todo' && b.progress == null)
            (b.id == firstTodoId ? TodoCard(latestItems) : const SizedBox.shrink())
          else
            _block(b),
      ],
    );
  }

  Widget _block(Block b) => switch (b) {
        // 流式中的空块(delta 先建块后填内容)渲染成孤立小方块很突兀,直接跳过
        ThinkingBlock(:final text) when text.trim().isEmpty =>
          const SizedBox.shrink(),
        TextBlock(:final text) when text.trim().isEmpty =>
          const SizedBox.shrink(),
        ThinkingBlock(:final text) => _Thinking(text),
        TextBlock(:final text) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: _ChatMarkdown(text),
          ),
        ToolBlock() => _ToolCard(b, onApprove),
        SubagentBlock() => _SubagentCard(b),
      };
}

/// 聊天正文 markdown:inline code 里的工作区路径 → 可点链接(文件开预览 / 目录进文件
/// 管理)。与 @ 引用共用 fileIndexProvider;索引未加载时按普通 code 渲染,渐进增强。
class _ChatMarkdown extends ConsumerWidget {
  final String text;
  const _ChatMarkdown(this.text);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final index = ref.watch(fileIndexProvider).asData?.value ?? const <String>[];
    // key 随「索引是否就绪」变化:flutter_markdown 仅在 data/styleSheet 变化时重解析
    // (didUpdateWidget 门槛),索引异步到位后只换 builders 不会重建 children ——
    // 历史消息的路径链接会永不出现(审查高危,已实测坐实)。换 key 强制重建 State 重解析。
    return MarkdownBody(
      key: ValueKey(index.isEmpty),
      data: text,
      shrinkWrap: true,
      styleSheet: _md,
      builders: index.isEmpty
          ? const {}
          : {'code': _PathLinkCodeBuilder(index, context)},
    );
  }
}

/// inline code 定制:命中工作区路径 → teal 下划线可点;未命中/块级(含换行)返回 null
/// 走默认渲染。文件 → /files 自动预览;目录 → /files 定位到该目录。
class _PathLinkCodeBuilder extends MarkdownElementBuilder {
  final List<String> index;
  final BuildContext context;
  _PathLinkCodeBuilder(this.index, this.context);

  @override
  Widget? visitElementAfter(md.Element element, TextStyle? preferredStyle) {
    final text = element.textContent;
    if (text.contains('\n')) return null; // 块级代码走默认
    final hit = resolveWorkspacePath(text, index);
    if (hit == null) return null;
    final dir = hit.isDir
        ? hit.path
        : (hit.path.contains('/')
            ? hit.path.substring(0, hit.path.lastIndexOf('/'))
            : '');
    final query = hit.isDir
        ? 'dir=${Uri.encodeComponent(dir)}'
        : 'dir=${Uri.encodeComponent(dir)}&preview=${Uri.encodeComponent(hit.path)}';
    return GestureDetector(
      onTap: () => context.push('/files?$query'),
      child: Text(
        text,
        style: const TextStyle(
          fontSize: 13,
          fontFamily: 'monospace',
          color: AppTheme.teal,
          decoration: TextDecoration.underline,
          decorationColor: AppTheme.teal,
          backgroundColor: AppTheme.tealSoft,
        ),
      ),
    );
  }
}

final _md = MarkdownStyleSheet(
  // 表格列平分宽度:flutter_markdown 默认 IntrinsicColumnWidth,列多必横向溢出报错;
  // Flex 平分让单元格自动换行,窄屏安全(牺牲少量对齐美观)。
  tableColumnWidth: const FlexColumnWidth(),
  p: const TextStyle(fontSize: 15, height: 1.5, color: AppTheme.ink),
  code: const TextStyle(
      fontSize: 13,
      fontFamily: 'monospace',
      color: AppTheme.ink,
      backgroundColor: AppTheme.borderSoft),
  codeblockPadding: const EdgeInsets.all(12),
  codeblockDecoration: BoxDecoration(
    color: AppTheme.bg,
    borderRadius: BorderRadius.circular(10),
    border: Border.all(color: AppTheme.border),
  ),
  blockquoteDecoration: BoxDecoration(
      color: AppTheme.tealSoft, borderRadius: BorderRadius.circular(8)),
  h1: const TextStyle(
      fontSize: 20, fontWeight: FontWeight.w700, color: AppTheme.ink),
  h2: const TextStyle(
      fontSize: 18, fontWeight: FontWeight.w700, color: AppTheme.ink),
  h3: const TextStyle(
      fontSize: 16, fontWeight: FontWeight.w600, color: AppTheme.ink),
  a: const TextStyle(color: AppTheme.teal),
  listBullet: const TextStyle(fontSize: 15, color: AppTheme.ink),
);

class _Thinking extends StatelessWidget {
  final String text;
  const _Thinking(this.text);
  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.symmetric(vertical: 6),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppTheme.bg,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppTheme.borderSoft),
        ),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Icon(Icons.auto_awesome, size: 15, color: AppTheme.faint),
          const SizedBox(width: 8),
          Expanded(
            child: Text(text,
                style: const TextStyle(
                    color: AppTheme.muted, fontSize: 13.5, height: 1.45)),
          ),
        ]),
      );
}

// 危险操作拦截结果里的批准码(worker danger.py 契约;含码即渲染确认按钮)
final _approvalRe = RegExp(r'批准码\s*([a-f0-9]{16})');

class _ToolCard extends StatelessWidget {
  final ToolBlock block;
  final void Function(String text)? onApprove;
  const _ToolCard(this.block, [this.onApprove]);
  @override
  Widget build(BuildContext context) {
    final done = block.result != null;
    final err = block.result?.isError ?? false;
    final color = err ? AppTheme.danger : AppTheme.teal;
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        border: Border.all(color: AppTheme.border),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(
            padding: const EdgeInsets.all(5),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(7),
            ),
            child: Icon(
                done ? (err ? Icons.error_outline : Icons.check) : Icons.bolt,
                size: 14,
                color: color),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(block.call.name,
                style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    fontSize: 13.5,
                    color: AppTheme.ink)),
          ),
          if (!done)
            const SizedBox(
                width: 12,
                height: 12,
                child: CircularProgressIndicator(strokeWidth: 1.6)),
        ]),
        // edit 工具:红绿 diff 直观展示替换内容(替代不可读的参数 JSON)
        if (block.call.name == 'edit') ...[
          if (block.call.arguments['path'] case final String p) ...[
            const SizedBox(height: 6),
            Text(p,
                style: const TextStyle(
                    fontSize: 12,
                    fontFamily: 'monospace',
                    color: AppTheme.muted)),
          ],
          const SizedBox(height: 6),
          EditDiffView(parseEdits(block.call.arguments)),
        ],
        if (block.result != null) ...[
          const SizedBox(height: 8),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
                color: AppTheme.bg, borderRadius: BorderRadius.circular(8)),
            child: Text(block.result!.content,
                maxLines: 6,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                    fontSize: 12,
                    color: AppTheme.muted,
                    fontFamily: 'monospace',
                    height: 1.4)),
          ),
        ],
        // 危险操作被拦:一键批准 —— 发送含批准码的确认消息,agent 下一回合重试即放行
        if (onApprove != null &&
            (block.result?.isError ?? false) &&
            _approvalRe.hasMatch(block.result!.content)) ...[
          const SizedBox(height: 8),
          Row(children: [
            const Expanded(
              child: Text('此操作有破坏性,已被拦截,需你确认',
                  style: TextStyle(fontSize: 12, color: Color(0xFFB45309))),
            ),
            FilledButton.tonal(
              style: FilledButton.styleFrom(
                backgroundColor: const Color(0xFFF59E0B),
                foregroundColor: Colors.white,
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                minimumSize: Size.zero,
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
              onPressed: () {
                final fp = _approvalRe
                    .firstMatch(block.result!.content)!
                    .group(1)!;
                onApprove!('允许执行该操作(批准码 $fp)');
              },
              child: const Text('允许执行并继续', style: TextStyle(fontSize: 12)),
            ),
          ]),
        ],
        // generate_image/edit_image:把生成的图直接在卡片内渲染
        if (_toolImagePath(block) case final p?) _GeneratedImage(p),
      ]),
    );
  }
}

/// generate_image/edit_image 生成的图:带 token 取字节后内嵌(复用 sentImageProvider 缓存)。
class _GeneratedImage extends ConsumerWidget {
  final String path;
  const _GeneratedImage(this.path);
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final img = ref.watch(sentImageProvider(path));
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(10),
        child: img.when(
          data: (bytes) =>
              Image.memory(bytes, width: double.infinity, fit: BoxFit.fitWidth),
          loading: () => Container(
              height: 140,
              color: AppTheme.bg,
              child: const Center(
                  child: SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2)))),
          error: (_, _) => Container(
              padding: const EdgeInsets.all(12),
              color: AppTheme.bg,
              child: Text('图片加载失败: $path',
                  style:
                      const TextStyle(fontSize: 11, color: AppTheme.faint))),
        ),
      ),
    );
  }
}

class _SubagentCard extends StatefulWidget {
  final SubagentBlock block;
  const _SubagentCard(this.block);
  @override
  State<_SubagentCard> createState() => _SubagentCardState();
}

class _SubagentCardState extends State<_SubagentCard> {
  bool _open = false;
  @override
  Widget build(BuildContext context) {
    final b = widget.block;
    final expanded = b.running || _open; // 运行强制展开,完成默认折叠
    final steps = b.blocks.whereType<ToolBlock>().length;
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 6),
      decoration: BoxDecoration(
        border: Border.all(color: _indigo.withValues(alpha: 0.3)),
        borderRadius: BorderRadius.circular(14),
        color: _indigoSoft,
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: b.running ? null : () => setState(() => _open = !_open),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(children: [
              const Icon(Icons.smart_toy_outlined, size: 16, color: _indigo),
              const SizedBox(width: 8),
              const Text('子 agent',
                  style: TextStyle(
                      fontWeight: FontWeight.w600,
                      fontSize: 13.5,
                      color: AppTheme.ink)),
              const SizedBox(width: 6),
              Expanded(
                child: Text(b.description,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: _indigo, fontSize: 13)),
              ),
              const SizedBox(width: 6),
              if (b.running)
                const SizedBox(
                    width: 12,
                    height: 12,
                    child: CircularProgressIndicator(
                        strokeWidth: 1.6, color: _indigo))
              else ...[
                Text('${b.ok ? "✓" : "✗"}${steps > 0 ? " $steps 步" : ""}',
                    style: const TextStyle(fontSize: 12, color: _indigo)),
                const SizedBox(width: 2),
                Icon(expanded ? Icons.expand_less : Icons.expand_more,
                    size: 18, color: _indigo.withValues(alpha: 0.6)),
              ],
            ]),
          ),
        ),
        if (expanded)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AppTheme.surface,
              border:
                  Border(top: BorderSide(color: _indigo.withValues(alpha: 0.15))),
              borderRadius:
                  const BorderRadius.vertical(bottom: Radius.circular(14)),
            ),
            child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (b.prompt.isNotEmpty)
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(10),
                      margin: const EdgeInsets.only(bottom: 10),
                      decoration: BoxDecoration(
                          color: _indigoSoft,
                          borderRadius: BorderRadius.circular(8)),
                      child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('任务指令',
                                style: TextStyle(
                                    fontSize: 11,
                                    fontWeight: FontWeight.w600,
                                    color: _indigo)),
                            const SizedBox(height: 3),
                            Text(b.prompt,
                                style: const TextStyle(
                                    fontSize: 12.5,
                                    color: AppTheme.muted,
                                    height: 1.4)),
                          ]),
                    ),
                  // 子 agent 内不放确认按钮(审查 M2):子 agent 是独立回合、批准码到不了
                  // 它的 user_message,按钮点了也放行不了;被拦 = 失败汇报。与 web 一致。
                  TurnBlocks(b.blocks, onApprove: null),
                ]),
          ),
      ]),
    );
  }
}
