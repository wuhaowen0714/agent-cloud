import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/features/auth/auth_controller.dart';
import 'package:agent_cloud_mobile/features/chat/chat_page.dart';

Dio _dio({void Function(DioAdapter)? extra}) {
  final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
  final a = DioAdapter(dio: dio);
  // 历史:一条用户提问 + 一条 assistant 回答 → 合成一个可长按操作的回合
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

void main() {
  testWidgets('长按用户气泡 → 弹出消息操作菜单(复制/分叉/回到这里)', (tester) async {
    await _pump(tester);
    expect(find.text('解释快排'), findsOneWidget);

    await tester.longPress(find.text('解释快排'));
    await tester.pumpAndSettle();

    expect(find.text('复制提问'), findsOneWidget);
    expect(find.text('复制回答'), findsOneWidget);
    expect(find.text('从这里分叉新会话'), findsOneWidget);
    expect(find.text('回到这里(删除其后)'), findsOneWidget);
  });

  testWidgets('复制提问 → 写入剪贴板 + 提示已复制', (tester) async {
    // 拦截剪贴板平台通道,记录写入内容
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

    await _pump(tester);
    await tester.longPress(find.text('解释快排'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('复制提问'));
    await tester.pumpAndSettle();

    expect(copied, '解释快排');
    expect(find.text('已复制'), findsOneWidget);
  });

  testWidgets('复制回答 → 拼接 assistant 正文', (tester) async {
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

    await _pump(tester);
    await tester.longPress(find.text('解释快排'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('复制回答'));
    await tester.pumpAndSettle();

    expect(copied, '快排是分治排序');
  });

  testWidgets('回到这里:会话忙(409)→ 干净文案,不露 DioException', (tester) async {
    await _pump(tester, extra: (a) {
      a.onPost(
        '/sessions/s1/rollback',
        (s) => s.reply(409, {'detail': 'session is busy'}),
        data: {'message_id': 'm1'},
      );
    });
    await tester.longPress(find.text('解释快排'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('回到这里(删除其后)'));
    await tester.pumpAndSettle();
    // 确认弹窗 → 删除
    await tester.tap(find.text('删除'));
    await tester.pumpAndSettle();

    expect(find.text('会话正忙,请稍候再试'), findsOneWidget);
    expect(find.textContaining('DioException'), findsNothing);
  });
}
