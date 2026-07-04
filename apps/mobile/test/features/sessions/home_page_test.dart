import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/features/sessions/home_page.dart';
import 'package:agent_cloud_mobile/features/auth/auth_controller.dart';
import 'package:agent_cloud_mobile/features/sessions/sessions_controller.dart';
import 'package:agent_cloud_mobile/models/agent_config.dart';

Dio _dio() {
  final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
  DioAdapter(dio: dio).onGet('/sessions', (s) => s.reply(200, []));
  return dio;
}

void main() {
  testWidgets('agent 栏末尾有 + 创建入口', (tester) async {
    await tester.pumpWidget(ProviderScope(
      overrides: [
        dioProvider.overrideWithValue(_dio()),
        agentsProvider.overrideWith(
            (ref) => Future.value([const AgentConfig(id: 'a1', name: 'main')])),
      ],
      child: const MaterialApp(home: HomePage()),
    ));
    await tester.pumpAndSettle();
    // 恰 2 个 add 图标:FAB 新对话 + agent 栏末位创建入口(AppBar 的新建智能体已删
    // ——与 FAB 双加号语义撞车,创建 agent 收敛到 agent 栏语境内)
    expect(find.byIcon(Icons.add), findsNWidgets(2));
    expect(find.text('main'), findsOneWidget);
  });

  testWidgets('会话卡副行显示最后消息预览(剥 marker),无预览回退模型名;未读显示圆点',
      (tester) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onGet('/sessions', (s) => s.reply(200, [
          {
            'id': 's1',
            'agent_config_id': 'a1',
            'model': 'DeepSeek-V4-Pro',
            'title': '带预览',
            'status': 'idle',
            'last_active_at': DateTime.now().toIso8601String(),
            'unread': true,
            'last_message':
                '好的,已完成\n\n[Uploaded file(s) in the workspace — read with read_file, or edit images with edit_image]\nuploads/x.png',
          },
          {
            'id': 's2',
            'agent_config_id': 'a1',
            'model': 'Kimi-K2.6',
            'title': '无预览',
            'status': 'idle',
            'last_active_at': DateTime.now().toIso8601String(),
          },
        ]));
    await tester.pumpWidget(ProviderScope(
      overrides: [
        dioProvider.overrideWithValue(dio),
        agentsProvider.overrideWith(
            (ref) => Future.value([const AgentConfig(id: 'a1', name: 'main')])),
      ],
      child: const MaterialApp(home: HomePage()),
    ));
    await tester.pumpAndSettle();
    expect(find.text('好的,已完成'), findsOneWidget); // marker 已剥、换行压掉
    expect(find.text('Kimi-K2.6'), findsOneWidget); // 无预览 → 模型名兜底
    expect(find.textContaining('Uploaded file'), findsNothing);
  });
}
