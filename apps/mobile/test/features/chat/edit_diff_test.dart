import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:agent_cloud_mobile/features/chat/edit_diff.dart';

void main() {
  test('parseEdits:合法项解析,非法项丢弃', () {
    final edits = parseEdits({
      'edits': [
        {'old_text': 'a', 'new_text': 'b'},
        {'old_text': 1, 'new_text': 'x'}, // 非法丢
        'junk',
      ],
    });
    expect(edits, [(oldText: 'a', newText: 'b')]);
    expect(parseEdits({}), isEmpty);
    expect(parseEdits({'edits': 'x'}), isEmpty);
  });

  testWidgets('EditDiffView 渲染 - 旧行 / + 新行', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: EditDiffView(const [
          (oldText: 'old line', newText: 'new line'),
        ]),
      ),
    ));
    expect(find.textContaining('- old line'), findsOneWidget);
    expect(find.textContaining('+ new line'), findsOneWidget);
  });
}
