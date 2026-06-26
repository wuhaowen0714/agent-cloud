import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/theme/app_theme.dart';
import '../files/files_repository.dart'; // sentImageProvider(带 token 取图)
import '../../models/block.dart';

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
  const TurnBlocks(this.blocks, {super.key});

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [for (final b in blocks) _block(b)],
      );

  Widget _block(Block b) => switch (b) {
        ThinkingBlock(:final text) => _Thinking(text),
        TextBlock(:final text) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: MarkdownBody(data: text, shrinkWrap: true, styleSheet: _md),
          ),
        ToolBlock() => _ToolCard(b),
        SubagentBlock() => _SubagentCard(b),
      };
}

final _md = MarkdownStyleSheet(
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

class _ToolCard extends StatelessWidget {
  final ToolBlock block;
  const _ToolCard(this.block);
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
                  TurnBlocks(b.blocks), // 递归渲染子过程
                ]),
          ),
      ]),
    );
  }
}
