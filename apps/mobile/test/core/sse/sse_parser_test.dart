import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:agent_cloud_mobile/core/sse/sse_parser.dart';
import 'package:agent_cloud_mobile/models/turn_event.dart';

void main() {
  test('解析 data: 行 → TurnEvent', () async {
    const raw = 'data: {"type":"text_delta","text":"hi"}\n\n'
        'data: {"type":"turn_done"}\n\n';
    final bytes = Stream.value(Uint8List.fromList(utf8.encode(raw)));
    final events = await parseSse(bytes).toList();
    expect(events.length, 2);
    expect((events[0] as TextDelta).text, 'hi');
    expect(events[1], isA<TurnDoneEvent>());
  });

  test('跨 chunk 拼接一个事件', () async {
    final bytes = Stream.fromIterable([
      Uint8List.fromList(utf8.encode('data: {"type":"text_de')),
      Uint8List.fromList(utf8.encode('lta","text":"x"}\n\n')),
    ]);
    final events = await parseSse(bytes).toList();
    expect((events.single as TextDelta).text, 'x');
  });

  test('子 agent 事件带 subagent_id', () async {
    const raw =
        'data: {"type":"text_delta","text":"子","subagent_id":"sub-1"}\n\n';
    final bytes = Stream.value(Uint8List.fromList(utf8.encode(raw)));
    final e = (await parseSse(bytes).toList()).single as TextDelta;
    expect(e.subagentId, 'sub-1');
  });
}
