import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/features/agent/agent_memory_page.dart';
import 'package:agent_cloud_mobile/features/auth/auth_controller.dart';

Dio _dio() {
  final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
  DioAdapter(dio: dio).onGet('/memory',
      (s) => s.reply(200,
          {'scope': 'agent', 'owner_id': 'a1', 'content': '记得偏好', 'version': 1}),
      queryParameters: {'scope': 'agent', 'agent_id': 'a1'});
  return dio;
}

void main() {
  testWidgets('加载并显示 agent 记忆内容', (tester) async {
    await tester.pumpWidget(ProviderScope(
      overrides: [dioProvider.overrideWithValue(_dio())],
      child: const MaterialApp(home: AgentMemoryPage('a1')),
    ));
    await tester.pumpAndSettle();
    expect(find.text('记得偏好'), findsOneWidget);
    expect(find.text('保存'), findsOneWidget);
  });
}
