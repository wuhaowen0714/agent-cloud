import '../../models/block.dart';
import '../../models/message.dart';
import '../../models/turn_event.dart';

// ── 流式:把事件应用到 blocks(对标 web blocks.ts)──

/// thinking/text 增量:尾块同类追加,否则新开。
List<Block> appendDelta(List<Block> blocks, {required bool thinking, required String text}) {
  final last = blocks.isNotEmpty ? blocks.last : null;
  if (thinking && last is ThinkingBlock) {
    return [...blocks.take(blocks.length - 1), ThinkingBlock(last.id, last.text + text)];
  }
  if (!thinking && last is TextBlock) {
    return [...blocks.take(blocks.length - 1), TextBlock(last.id, last.text + text)];
  }
  final id = '${thinking ? 'thinking' : 'text'}-${blocks.length}';
  return [...blocks, thinking ? ThinkingBlock(id, text) : TextBlock(id, text)];
}

/// 工具调用新开块(以 call.id 为 key);已有同 id 则原位替换。
List<Block> appendToolCall(List<Block> blocks, ToolCall call) {
  final i = blocks.indexWhere((b) => b is ToolBlock && b.id == call.id);
  final block = ToolBlock(call.id, call);
  if (i == -1) return [...blocks, block];
  return [...blocks.take(i), block, ...blocks.skip(i + 1)];
}

/// 工具结果按 call_id 回填。
List<Block> attachToolResult(List<Block> blocks, String callId, ToolResult result) {
  return blocks
      .map((b) => (b is ToolBlock && b.call.id == callId)
          ? ToolBlock(b.id, b.call, result: result, progress: b.progress)
          : b)
      .toList();
}

/// 把一个流事件应用到一组 blocks(顶层与子 agent 内部共用)。
List<Block> applyEvent(List<Block> blocks, TurnEvent e) {
  switch (e) {
    case ThinkingDelta(:final text):
      return appendDelta(blocks, thinking: true, text: text);
    case TextDelta(:final text):
      return appendDelta(blocks, thinking: false, text: text);
    case ToolCallStart(:final callId, :final tool, :final args):
      // task 由 subagent 卡承载,顶层不建工具卡(防 live 重复)。
      if (tool == 'task') return blocks;
      return appendToolCall(
          blocks, ToolCall(id: callId, name: tool, arguments: args));
    case ToolResultDelta(:final callId, :final result, :final isError):
      return attachToolResult(blocks, callId,
          ToolResult(callId: callId, content: result, isError: isError));
    default:
      return blocks;
  }
}

// ── 子 agent 折叠卡 ──

List<Block> startSubagent(
    List<Block> blocks, String id, String description, String prompt) {
  if (blocks.any((b) => b is SubagentBlock && b.id == id)) return blocks;
  return [
    ...blocks,
    SubagentBlock(id,
        description: description,
        prompt: prompt,
        blocks: const [],
        running: true,
        ok: true),
  ];
}

List<Block> appendToSubagent(List<Block> blocks, String id, TurnEvent e) {
  return blocks
      .map((b) => (b is SubagentBlock && b.id == id)
          ? SubagentBlock(b.id,
              description: b.description,
              prompt: b.prompt,
              blocks: applyEvent(b.blocks, e),
              running: b.running,
              ok: b.ok)
          : b)
      .toList();
}

List<Block> finishSubagent(List<Block> blocks, String id, bool ok) {
  return blocks
      .map((b) => (b is SubagentBlock && b.id == id)
          ? SubagentBlock(b.id,
              description: b.description,
              prompt: b.prompt,
              blocks: b.blocks,
              running: false,
              ok: ok)
          : b)
      .toList();
}

// ── 历史重建(对标 web rebuildBlocks + messagesToTurns)──

class Turn {
  final String id;
  final String? userText;
  final List<Block> blocks;
  const Turn(this.id, this.userText, this.blocks);
}

/// 一组消息 → blocks;task 调用渲染成 subagent 卡(内部由 parentCallId 子消息递归重建)。
List<Block> rebuildBlocks(
    List<Message> msgs, Map<String, List<Message>> subByCall) {
  final results = <String, ToolResult>{};
  for (final m in msgs) {
    if (m.role == 'tool') {
      for (final r in m.content.toolResults) {
        results[r.callId] = r;
      }
    }
  }
  final blocks = <Block>[];
  for (final m in msgs) {
    if (m.role == 'tool') continue;
    if (m.content.text.isNotEmpty) {
      blocks.add(TextBlock('${m.id}-text', m.content.text));
    }
    for (final c in m.content.toolCalls) {
      if (c.name == 'task') {
        final r = results[c.id];
        final desc = c.arguments['description'];
        final prompt = c.arguments['prompt'];
        final subMsgs = subByCall[c.id] ?? const [];
        final inner = subMsgs.isNotEmpty
            ? rebuildBlocks(subMsgs, subByCall)
            : (r != null ? [TextBlock('${c.id}-r', r.content)] : <Block>[]);
        blocks.add(SubagentBlock(c.id,
            description: desc is String ? desc : '子任务',
            prompt: prompt is String ? prompt : '',
            blocks: inner,
            running: false,
            ok: !(r?.isError ?? false)));
      } else {
        blocks.add(ToolBlock(c.id, c, result: results[c.id]));
      }
    }
  }
  return blocks;
}

/// 历史消息 → 回合。user 消息起新回合;子消息(parentCallId)先剔出、重建进卡。
List<Turn> messagesToTurns(List<Message> messages) {
  final subByCall = <String, List<Message>>{};
  final mains = <Message>[];
  for (final m in messages) {
    final pid = m.content.parentCallId;
    if (pid != null && pid.isNotEmpty) {
      (subByCall[pid] ??= []).add(m);
    } else {
      mains.add(m);
    }
  }
  final turns = <Turn>[];
  String? curId;
  String? curUser;
  var curMsgs = <Message>[];
  void flush() {
    if (curId == null) return;
    turns.add(Turn(curId!, curUser, rebuildBlocks(curMsgs, subByCall)));
    curId = null;
    curUser = null;
    curMsgs = [];
  }

  for (final m in mains) {
    if (m.role == 'user') {
      flush();
      curId = m.id;
      curUser = m.content.text;
      curMsgs = [];
    } else {
      curId ??= m.id;
      curMsgs.add(m);
    }
  }
  flush();
  return turns;
}
