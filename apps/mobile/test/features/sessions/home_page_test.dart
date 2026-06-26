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
    // 恰 3 个 add 图标:AppBar 新建 + FAB 新对话 + agent 栏末位创建入口
    expect(find.byIcon(Icons.add), findsNWidgets(3));
    expect(find.text('main'), findsOneWidget);
  });
}
