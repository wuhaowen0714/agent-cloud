import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/features/chat/chat_repository.dart';

void main() {
  test('rollback POST + 返回 user_text', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onPost(
      '/sessions/s1/rollback',
      (s) => s.reply(200, {'deleted_count': 3, 'user_text': '重新问这个'}),
      data: {'message_id': 'm5'},
    );
    final text = await ChatRepository(dio).rollback('s1', 'm5');
    expect(text, '重新问这个');
  });

  test('rollback 缺 user_text 容错为空串', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onPost(
      '/sessions/s1/rollback',
      (s) => s.reply(200, {'deleted_count': 0}),
      data: {'message_id': 'm5'},
    );
    expect(await ChatRepository(dio).rollback('s1', 'm5'), '');
  });

  test('fork POST + 返回新会话 id 与 user_text', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onPost(
      '/sessions/s1/fork',
      (s) => s.reply(200, {'new_session_id': 's2', 'user_text': '从这里分叉'}),
      data: {'message_id': 'm5'},
    );
    final r = await ChatRepository(dio).fork('s1', 'm5');
    expect(r.newSessionId, 's2');
    expect(r.userText, '从这里分叉');
  });

  test('rollback 会话忙 → 抛 DioException(交给 UI 提示)', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onPost(
      '/sessions/s1/rollback',
      (s) => s.reply(409, {'detail': 'session is busy'}),
      data: {'message_id': 'm5'},
    );
    await expectLater(
        ChatRepository(dio).rollback('s1', 'm5'), throwsA(isA<DioException>()));
  });
}
