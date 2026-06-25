import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import '../../models/block.dart';

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
        TextBlock(:final text) =>
          MarkdownBody(data: text, shrinkWrap: true),
        ToolBlock() => _ToolCard(b),
        SubagentBlock() => _SubagentCard(b),
      };
}

class _Thinking extends StatelessWidget {
  final String text;
  const _Thinking(this.text);
  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
            color: Colors.grey.shade100,
            borderRadius: BorderRadius.circular(8)),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(Icons.psychology, size: 14, color: Colors.grey.shade500),
          const SizedBox(width: 6),
          Expanded(
              child: Text(text,
                  style:
                      TextStyle(color: Colors.grey.shade600, fontSize: 13))),
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
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 4),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        border: Border.all(color: Colors.grey.shade300),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(done ? (err ? Icons.error : Icons.check_circle) : Icons.bolt,
              size: 14, color: err ? Colors.red : Colors.teal),
          const SizedBox(width: 6),
          Text(block.call.name,
              style:
                  const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
        ]),
        if (block.result != null) ...[
          const SizedBox(height: 6),
          Text(block.result!.content,
              maxLines: 6,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                  fontSize: 12,
                  color: Colors.grey.shade700,
                  fontFamily: 'monospace')),
        ],
      ]),
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
        border: Border.all(color: Colors.lightBlue.shade200),
        borderRadius: BorderRadius.circular(12),
        color: Colors.lightBlue.shade50,
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        InkWell(
          onTap: b.running ? null : () => setState(() => _open = !_open),
          child: Padding(
            padding: const EdgeInsets.all(10),
            child: Row(children: [
              Icon(Icons.smart_toy,
                  size: 15, color: Colors.lightBlue.shade600),
              const SizedBox(width: 6),
              const Text('子 agent',
                  style:
                      TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
              const SizedBox(width: 4),
              Expanded(
                  child: Text('· ${b.description}',
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                          color: Colors.lightBlue.shade800, fontSize: 13))),
              Text(
                  b.running
                      ? '运行中…'
                      : '${b.ok ? "✓" : "✗"}${steps > 0 ? " $steps 步" : ""}',
                  style: TextStyle(
                      fontSize: 12, color: Colors.lightBlue.shade600)),
              if (!b.running)
                Icon(expanded ? Icons.expand_less : Icons.expand_more,
                    size: 16, color: Colors.lightBlue.shade400),
            ]),
          ),
        ),
        if (expanded)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: Colors.white,
              border:
                  Border(top: BorderSide(color: Colors.lightBlue.shade100)),
              borderRadius: const BorderRadius.vertical(
                  bottom: Radius.circular(12)),
            ),
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (b.prompt.isNotEmpty)
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(8),
                  margin: const EdgeInsets.only(bottom: 8),
                  decoration: BoxDecoration(
                      color: Colors.lightBlue.shade50,
                      borderRadius: BorderRadius.circular(8)),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('任务指令',
                            style: TextStyle(
                                fontSize: 11,
                                fontWeight: FontWeight.w600,
                                color: Colors.lightBlue.shade600)),
                        const SizedBox(height: 2),
                        Text(b.prompt,
                            style: TextStyle(
                                fontSize: 12, color: Colors.grey.shade600)),
                      ]),
                ),
              TurnBlocks(b.blocks), // 递归渲染子过程
            ]),
          ),
      ]),
    );
  }
}
