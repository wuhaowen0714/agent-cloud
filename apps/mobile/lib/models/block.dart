import 'message.dart';

/// 工具参数生成中的进度(pending 卡)。
class ToolProgress {
  final int argsChars;
  final int lines;
  final String path;
  const ToolProgress(this.argsChars, this.lines, this.path);
}

/// 一个回合按时间顺序拆成的展示块(对标 web blocks.ts 的 Block)。
sealed class Block {
  final String id;
  const Block(this.id);
}

class ThinkingBlock extends Block {
  final String text;
  const ThinkingBlock(super.id, this.text);
}

class TextBlock extends Block {
  final String text;
  const TextBlock(super.id, this.text);
}

class ToolBlock extends Block {
  final ToolCall call;
  final ToolResult? result;
  final ToolProgress? progress;
  const ToolBlock(super.id, this.call, {this.result, this.progress});
}

/// 子 agent(task 派生)折叠卡:同 subagent_id 的事件收拢进内部 blocks。
class SubagentBlock extends Block {
  final String description;
  final String prompt;
  final List<Block> blocks;
  final bool running;
  final bool ok;
  const SubagentBlock(
    super.id, {
    required this.description,
    required this.prompt,
    required this.blocks,
    required this.running,
    required this.ok,
  });
}
