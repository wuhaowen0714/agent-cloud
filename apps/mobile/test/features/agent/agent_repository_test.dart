import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/features/agent/agent_repository.dart';

void main() {
  test('getAgentInstructions 取 AGENTS content', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onGet('/context-documents',
        (s) => s.reply(200, [
              {'id': 'd1', 'scope': 'agent', 'type': 'AGENTS', 'owner_id': 'a1', 'content': '你是客服'},
            ]),
        queryParameters: {'scope': 'agent', 'agent_id': 'a1'});
    expect(await AgentRepository(dio).getAgentInstructions('a1'), '你是客服');
  });

  test('getAgentInstructions 无 AGENTS → 空串', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onGet('/context-documents',
        (s) => s.reply(200, []),
        queryParameters: {'scope': 'agent', 'agent_id': 'a1'});
    expect(await AgentRepository(dio).getAgentInstructions('a1'), '');
  });

  test('putAgentInstructions PUT body', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onPut('/context-documents',
        (s) => s.reply(200, {'id': 'd1', 'scope': 'agent', 'type': 'AGENTS', 'owner_id': 'a1', 'content': 'x'}),
        data: {'scope': 'agent', 'type': 'AGENTS', 'content': 'x', 'agent_id': 'a1'});
    await AgentRepository(dio).putAgentInstructions('a1', 'x');
  });

  test('getAgentMemory 取 content', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onGet('/memory',
        (s) => s.reply(200, {'scope': 'agent', 'owner_id': 'a1', 'content': '偏好简洁', 'version': 1}),
        queryParameters: {'scope': 'agent', 'agent_id': 'a1'});
    expect(await AgentRepository(dio).getAgentMemory('a1'), '偏好简洁');
  });

  test('putAgentMemory PUT body', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onPut('/memory',
        (s) => s.reply(200, {'scope': 'agent', 'owner_id': 'a1', 'content': 'x', 'version': 2}),
        data: {'scope': 'agent', 'content': 'x', 'agent_id': 'a1'});
    await AgentRepository(dio).putAgentMemory('a1', 'x');
  });

  test('clearAgentMemory DELETE query', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onDelete('/memory',
        (s) => s.reply(200, {'scope': 'agent', 'owner_id': 'a1', 'content': '', 'version': 3}),
        queryParameters: {'scope': 'agent', 'agent_id': 'a1'});
    await AgentRepository(dio).clearAgentMemory('a1');
  });
}
