import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/features/sessions/sessions_repository.dart';

void main() {
  test('listSessions 解析列表', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onGet(
      '/sessions',
      (s) => s.reply(200, [
        {
          'id': 's1',
          'agent_config_id': 'a1',
          'model': 'm',
          'title': 'hi',
          'status': 'idle',
        },
      ]),
    );
    final sessions = await SessionsRepository(dio).listSessions();
    expect(sessions.length, 1);
    expect(sessions.first.title, 'hi');
  });

  test('createSession POST + 解析', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onPost(
      '/sessions',
      (s) => s.reply(201, {
        'id': 's2',
        'agent_config_id': 'a1',
        'model': 'm',
        'title': null,
        'status': 'idle',
      }),
      data: {'agent_config_id': 'a1'},
    );
    final session = await SessionsRepository(dio).createSession('a1');
    expect(session.id, 's2');
    expect(session.displayTitle, '新会话');
  });

  test('listAgents 解析', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onGet('/agent-configs',
        (s) => s.reply(200, [{'id': 'a1', 'name': 'main'}]));
    final agents = await SessionsRepository(dio).listAgents();
    expect(agents.single.name, 'main');
  });
}
