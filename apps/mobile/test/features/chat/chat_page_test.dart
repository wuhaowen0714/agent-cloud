import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/features/auth/auth_controller.dart';
import 'package:agent_cloud_mobile/features/chat/chat_controller.dart';
import 'package:agent_cloud_mobile/features/chat/chat_page.dart';

Dio _dio({void Function(DioAdapter)? extra}) {
  final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
  final a = DioAdapter(dio: dio);
  // 历史:两轮问答 → 「重新生成」仅出现在最后一轮的操作栏
  a.onGet('/sessions/s1/messages', (s) => s.reply(200, [
        {
          'id': 'm1',
          'seq': 0,
          'role': 'user',
          'content': {'text': '解释快排'},
        },
        {
          'id': 'm2',
          'seq': 1,
          'role': 'assistant',
          'content': {'text': '快排是分治排序'},
        },
        {
          'id': 'm3',
          'seq': 2,
          'role': 'user',
          'content': {'text': '再举个例子'},
        },
        {
          'id': 'm4',
          'seq': 3,
          'role': 'assistant',
          'content': {'text': '例如 [3,1,2] 排成 [1,2,3]'},
        },
      ]));
  // resume:无进行中回合
  a.onGet('/sessions/s1/turn/stream', (s) => s.reply(204, null));
  // 会话列表(AppBar 标题 / sessionsController)
  a.onGet('/sessions', (s) => s.reply(200, [
        {
          'id': 's1',
          'agent_config_id': 'a1',
          'model': 'm',
          'title': '快排',
          'status': 'idle',
        },
      ]));
  extra?.call(a);
  return dio;
}

Future<void> _pump(WidgetTester tester, {void Function(DioAdapter)? extra}) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [dioProvider.overrideWithValue(_dio(extra: extra))],
    child: const MaterialApp(home: ChatPage('s1')),
  ));
  await tester.pumpAndSettle();
}

/// 拦截剪贴板平台通道,返回一个读取「最后复制内容」的取值器。
String? Function() _mockClipboard() {
  final mgr = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  String? copied;
  mgr.setMockMethodCallHandler(SystemChannels.platform, (call) async {
    if (call.method == 'Clipboard.setData') {
      copied = (call.arguments as Map)['text'] as String?;
    }
    return null;
  });
  addTearDown(
      () => mgr.setMockMethodCallHandler(SystemChannels.platform, null));
  return () => copied;
}

void main() {
  testWidgets('回答下方常驻操作栏:复制/分叉/回到这里(无需长按直接可见)', (tester) async {
    await _pump(tester);
    expect(find.text('解释快排'), findsOneWidget);
    // 操作栏直接渲染在回答下方,不靠长按
    expect(find.byTooltip('复制'), findsNWidgets(2)); // 两轮各一
    expect(find.byTooltip('分叉'), findsNWidgets(2));
    expect(find.byTooltip('回到这里'), findsNWidgets(2));
    expect(find.byTooltip('重新生成'), findsOneWidget); // 仅最后一轮
  });

  testWidgets('点操作栏「复制」→ 复制回答正文 + 提示已复制', (tester) async {
    final copied = _mockClipboard();
    await _pump(tester);
    await tester.tap(find.byTooltip('复制').first); // 第一轮的复制
    await tester.pumpAndSettle();
    expect(copied(), '快排是分治排序');
    expect(find.text('已复制'), findsOneWidget);
  });

  testWidgets('长按用户气泡 → 直接复制提问(不弹菜单)', (tester) async {
    final copied = _mockClipboard();
    await _pump(tester);
    await tester.longPress(find.text('解释快排'));
    await tester.pumpAndSettle();
    expect(copied(), '解释快排');
    expect(find.text('已复制'), findsOneWidget);
  });

  testWidgets('点「回到这里」→ 确认 → 会话忙(409)给干净文案,不露 DioException', (tester) async {
    await _pump(tester, extra: (a) {
      a.onPost(
        '/sessions/s1/rollback',
        (s) => s.reply(409, {'detail': 'session is busy'}),
        data: {'message_id': 'm1'},
      );
    });
    await tester.tap(find.byTooltip('回到这里').first); // 第一轮(mock 的 m1)
    await tester.pumpAndSettle();
    // 确认弹窗 → 删除
    await tester.tap(find.text('删除'));
    await tester.pumpAndSettle();

    expect(find.text('会话正忙,请稍候再试'), findsOneWidget);
    expect(find.textContaining('DioException'), findsNothing);
  });

  testWidgets('输入 / → 弹技能浮层,选中 → 技能 chip + 输入框清空', (tester) async {
    await _pump(tester, extra: (a) {
      a.onGet('/skills', (s) => s.reply(200, [
            {
              'id': 'sk1',
              'name': '文档整理',
              'description': '整理文档',
              'source': 'builtin',
              'version': '1'
            },
          ]));
      a.onGet('/agent-configs/a1/skills', (s) => s.reply(200, const []));
      a.onPut('/agent-configs/a1/skills', (s) => s.reply(200, null),
          data: {
            'skill_ids': ['sk1']
          });
    });
    await tester.enterText(find.byType(TextField), '/');
    await tester.pumpAndSettle();
    expect(find.text('文档整理'), findsOneWidget); // 技能浮层条目

    await tester.tap(find.text('文档整理'));
    await tester.pumpAndSettle();
    // 选中后:输入框清空,技能成 chip(仍能找到「文档整理」——这次是 chip)
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text, '');
    expect(find.text('文档整理'), findsOneWidget);
  });

  testWidgets('输入 @词 → 弹文件浮层,选中 → 插入 @路径 到输入框', (tester) async {
    await _pump(tester, extra: (a) {
      a.onGet('/files/index',
          (s) => s.reply(200, ['notes/plan.md', 'src/main.dart']));
    });
    await tester.enterText(find.byType(TextField), '@plan');
    await tester.pumpAndSettle();
    expect(find.text('plan.md'), findsOneWidget); // 浮层项 title=basename

    await tester.tap(find.text('plan.md'));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text,
        '@notes/plan.md ');
  });

  testWidgets('正文以 / 开头但是路径(/usr/bin)→ 不误弹技能浮层', (tester) async {
    await _pump(tester, extra: (a) {
      a.onGet('/skills', (s) => s.reply(200, [
            {
              'id': 'sk1',
              'name': '文档整理',
              'description': 'x',
              'source': 'b',
              'version': '1'
            },
          ]));
    });
    await tester.enterText(find.byType(TextField), '/usr/bin');
    await tester.pumpAndSettle();
    expect(find.text('文档整理'), findsNothing); // 含第二个 / → 不触发技能浮层
  });

  testWidgets('重新生成:仅最后一轮显示;点击 → rollback(m3)后自动重发原文', (tester) async {
    var rolledBack = false;
    await _pump(tester, extra: (a) {
      a.onPost(
        '/sessions/s1/rollback',
        (s) {
          rolledBack = true;
          return s.reply(200, {'deleted_count': 2, 'user_text': '再举个例子'});
        },
        data: {'message_id': 'm3'}, // 最后一轮的 user 消息 id
      );
    });
    // 两轮回合,但「重新生成」chip 只有一个(最后一轮)
    expect(find.byTooltip('重新生成'), findsOneWidget);
    expect(find.byTooltip('复制'), findsNWidgets(2)); // 其余操作两轮都有

    await tester.tap(find.byTooltip('重新生成'));
    await tester.pump(const Duration(milliseconds: 300));
    expect(rolledBack, isTrue); // rollback 已按最后一轮的 id 发出
    // 随后自动重发原文:send 走 turn/stream(mock 未配 → 落 failedMessage,内容即原文)
    final st = ProviderScope.containerOf(tester.element(find.byType(ChatPage)))
        .read(chatControllerProvider('s1'));
    expect(st.liveUser == '再举个例子' || st.failedMessage == '再举个例子', isTrue);
  });

  testWidgets('附件按钮 → 弹菜单含「拍照」与「相册 / 文件」', (tester) async {
    await _pump(tester);
    await tester.tap(find.byIcon(Icons.attach_file));
    await tester.pumpAndSettle();
    expect(find.text('拍照'), findsOneWidget);
    expect(find.text('相册 / 文件'), findsOneWidget);
  });

  testWidgets('@ 浮层点 ✕ → 关闭', (tester) async {
    await _pump(tester, extra: (a) {
      a.onGet('/files/index', (s) => s.reply(200, ['notes/plan.md']));
    });
    await tester.enterText(find.byType(TextField), '@plan');
    await tester.pumpAndSettle();
    expect(find.text('plan.md'), findsOneWidget); // 浮层在
    await tester.tap(find.byIcon(Icons.close).first); // 点 ✕
    await tester.pumpAndSettle();
    expect(find.text('plan.md'), findsNothing); // 浮层已关闭
  });
}
