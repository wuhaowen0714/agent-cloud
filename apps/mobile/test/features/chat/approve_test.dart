import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:agent_cloud_mobile/features/chat/turn_blocks.dart';
import 'package:agent_cloud_mobile/features/files/files_repository.dart';
import 'package:agent_cloud_mobile/models/block.dart';
import 'package:agent_cloud_mobile/models/message.dart';

void main() {
  Widget wrap(Widget child) => ProviderScope(
        overrides: [
          fileIndexProvider.overrideWith((ref) => Future.value(const <String>[])),
        ],
        child: MaterialApp(home: Scaffold(body: SingleChildScrollView(child: child))),
      );

  ToolBlock blocked() => ToolBlock(
      'c1',
      ToolCall(id: 'c1', name: 'bash', arguments: {'command': 'rm -rf build'}),
      result: ToolResult(
          callId: 'c1',
          content: '⚠️ 已拦截可能有破坏性的操作:递归强制删除(rm -rf)(批准码 abcd1234abcd1234)。',
          isError: true));

  testWidgets('被拦结果 → 渲染确认按钮,点击发送含批准码的确认消息', (tester) async {
    String? sent;
    await tester.pumpWidget(wrap(
      TurnBlocks([blocked()], onApprove: (t) => sent = t),
    ));
    await tester.tap(find.text('允许执行并继续'));
    expect(sent, '允许执行该操作(批准码 abcd1234abcd1234)');
  });

  testWidgets('普通错误 / 无 onApprove → 不渲染按钮', (tester) async {
    final normalErr = ToolBlock(
        'c2',
        ToolCall(id: 'c2', name: 'bash', arguments: {'command': 'ls'}),
        result:
            ToolResult(callId: 'c2', content: 'not found', isError: true));
    await tester.pumpWidget(wrap(TurnBlocks([normalErr], onApprove: (_) {})));
    expect(find.text('允许执行并继续'), findsNothing);
    await tester.pumpWidget(wrap(TurnBlocks([blocked()]))); // 无 onApprove
    await tester.pumpAndSettle();
    expect(find.text('允许执行并继续'), findsNothing);
  });
}
