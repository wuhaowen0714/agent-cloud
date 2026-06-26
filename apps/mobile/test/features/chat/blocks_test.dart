import 'package:flutter_test/flutter_test.dart';
import 'package:agent_cloud_mobile/models/block.dart';
import 'package:agent_cloud_mobile/models/message.dart';
import 'package:agent_cloud_mobile/models/turn_event.dart';
import 'package:agent_cloud_mobile/features/chat/blocks.dart';

void main() {
  test('applyEvent 组装 thinking/text/tool + 回填结果', () {
    var b = <Block>[];
    b = applyEvent(b, const ThinkingDelta('想', null));
    b = applyEvent(b, const ToolCallStart('c1', 'bash', {}, null));
    b = applyEvent(b, const ToolResultDelta('c1', 'ok', false, null));
    expect(b[0], isA<ThinkingBlock>());
    expect(b[1], isA<ToolBlock>());
    expect((b[1] as ToolBlock).result?.content, 'ok');
  });

  test('applyEvent 拦 task 的 tool_call_start(由子卡承载)', () {
    final b = applyEvent([], const ToolCallStart('c1', 'task', {}, null));
    expect(b, isEmpty);
  });

  test('startSubagent 幂等 + appendToSubagent + finishSubagent', () {
    var b = startSubagent([], 'sub-1', '搜', 'p');
    expect(b.length, 1);
    b = startSubagent(b, 'sub-1', '搜', 'p'); // 同 id 不重开
    expect(b.length, 1);
    b = appendToSubagent(
        b, 'sub-1', const ToolCallStart('w1', 'web_search', {}, null));
    expect((b[0] as SubagentBlock).blocks.length, 1);
    b = finishSubagent(b, 'sub-1', true);
    expect((b[0] as SubagentBlock).running, false);
  });

  test('messagesToTurns:子消息按 parent_call_id 递归重建进 subagent 卡 + prompt', () {
    final messages = [
      const Message(
          id: 'u', seq: 0, role: 'user', content: MessageContent(text: '查')),
      const Message(
          id: 'a1',
          seq: 1,
          role: 'assistant',
          content: MessageContent(toolCalls: [
            ToolCall(
                id: 'task1',
                name: 'task',
                arguments: {'description': 'd', 'prompt': 'p'})
          ])),
      const Message(
          id: 's1',
          seq: 2,
          role: 'assistant',
          content: MessageContent(parentCallId: 'task1', toolCalls: [
            ToolCall(id: 'w1', name: 'web_search', arguments: {})
          ])),
      const Message(
          id: 's2',
          seq: 3,
          role: 'tool',
          content: MessageContent(parentCallId: 'task1', toolResults: [
            ToolResult(callId: 'w1', content: '结果', isError: false)
          ])),
      const Message(
          id: 'a2',
          seq: 4,
          role: 'assistant',
          content: MessageContent(text: '答')),
    ];
    final turns = messagesToTurns(messages);
    expect(turns.length, 1);
    final blocks = turns[0].blocks;
    // 顶层:subagent 卡 + 主回答文本(子消息不在顶层)
    expect(blocks.whereType<SubagentBlock>().length, 1);
    final card = blocks.whereType<SubagentBlock>().first;
    expect(card.prompt, 'p');
    // 卡内部重建出 web_search 工具(结果回填),而非只有结果文本
    final inner = card.blocks.whereType<ToolBlock>().first;
    expect(inner.call.name, 'web_search');
    expect(inner.result?.content, '结果');
  });
}
