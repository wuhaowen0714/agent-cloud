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
  // 历史:一条用户提问 + 一条 assistant 回答 → 合成一个带操作栏的历史回合
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
    expect(find.byTooltip('复制'), findsOneWidget);
    expect(find.byTooltip('分叉'), findsOneWidget);
    expect(find.byTooltip('回到这里'), findsOneWidget);
  });

  testWidgets('点操作栏「复制」→ 复制回答正文 + 提示已复制', (tester) async {
    final copied = _mockClipboard();
    await _pump(tester);
    await tester.tap(find.byTooltip('复制'));
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
    await tester.tap(find.byTooltip('回到这里'));
    await tester.pumpAndSettle();
    // 确认弹窗 → 删除
    await tester.tap(find.text('删除'));
    await tester.pumpAndSettle();

    expect(find.text('会话正忙,请稍候再试'), findsOneWidget);
    expect(find.textContaining('DioException'), findsNothing);
  });
}
