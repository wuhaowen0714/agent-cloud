import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:agent_cloud_mobile/features/chat/todo_card.dart';
import 'package:agent_cloud_mobile/features/chat/turn_blocks.dart';
import 'package:agent_cloud_mobile/models/block.dart';
import 'package:agent_cloud_mobile/models/message.dart';

void main() {
  test('parseTodoItems:合法项解析,非法项丢弃(不可信模型输出容错)', () {
    final items = parseTodoItems({
      'items': [
        {'content': '查资料', 'status': 'completed'},
        {'content': '写初稿', 'status': 'in_progress'},
        {'content': '', 'status': 'pending'}, // 空 content 丢
        {'content': 'x', 'status': 'done'}, // 非法 status 丢
        'not-a-map',
      ],
    });
    expect(items, [
      (content: '查资料', status: TodoStatus.completed),
      (content: '写初稿', status: TodoStatus.inProgress),
    ]);
    expect(parseTodoItems({}), isEmpty);
    expect(parseTodoItems({'items': 'x'}), isEmpty);
  });

  ToolBlock todoBlock(String id, List<Map<String, String>> items) => ToolBlock(
      id, ToolCall(id: id, name: 'todo', arguments: {'items': items}),
      result: ToolResult(callId: id, content: 'ok', isError: false));

  testWidgets('TodoCard 渲染进度与条目', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: TodoCard(const [
          (content: '查资料', status: TodoStatus.completed),
          (content: '写初稿', status: TodoStatus.inProgress),
          (content: '排版', status: TodoStatus.pending),
        ]),
      ),
    ));
    expect(find.text('任务清单'), findsOneWidget);
    expect(find.text('1/3'), findsOneWidget);
    expect(find.text('写初稿'), findsOneWidget);
  });

  testWidgets('TurnBlocks:多次 todo 只渲染一张卡(首现位置),内容取最新', (tester) async {
    final blocks = <Block>[
      todoBlock('t1', [
        {'content': 'a', 'status': 'pending'},
        {'content': 'b', 'status': 'pending'},
      ]),
      const TextBlock('x', '干活中'),
      todoBlock('t2', [
        {'content': 'a', 'status': 'completed'},
        {'content': 'b', 'status': 'in_progress'},
      ]),
    ];
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: SingleChildScrollView(child: TurnBlocks(blocks))),
    ));
    expect(find.text('任务清单'), findsOneWidget); // 只一张卡
    expect(find.text('1/2'), findsOneWidget); // 内容是最新一次
  });
}
