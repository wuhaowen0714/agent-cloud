import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/features/agent/agent_settings_page.dart';
import 'package:agent_cloud_mobile/features/auth/auth_controller.dart';
import 'package:agent_cloud_mobile/features/sessions/sessions_controller.dart';
import 'package:agent_cloud_mobile/models/agent_config.dart';

Dio _dio() {
  final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
  DioAdapter(dio: dio).onGet('/context-documents',
      (s) => s.reply(200, [
            {'id': 'd1', 'scope': 'agent', 'type': 'AGENTS', 'owner_id': 'a1', 'content': '你是客服'},
          ]),
      queryParameters: {'scope': 'agent', 'agent_id': 'a1'});
  return dio;
}

void main() {
  testWidgets('显示名称 + 人设 + 三个配置入口 + 删除', (tester) async {
    tester.view.physicalSize = const Size(1080, 2600);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(ProviderScope(
      overrides: [
        dioProvider.overrideWithValue(_dio()),
        agentsProvider.overrideWith(
            (ref) => Future.value([const AgentConfig(id: 'a1', name: '客服助手')])),
      ],
      child: const MaterialApp(home: AgentSettingsPage('a1')),
    ));
    await tester.pumpAndSettle();
    expect(find.text('客服助手'), findsOneWidget); // 名称
    expect(find.text('你是客服'), findsOneWidget); // 人设
    expect(find.text('工具'), findsOneWidget);
    expect(find.text('技能'), findsOneWidget);
    expect(find.text('记忆'), findsOneWidget);
    expect(find.text('删除此 Agent'), findsOneWidget);
  });
}
