import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/features/chat/chat_repository.dart';
import 'package:agent_cloud_mobile/models/turn_event.dart';

/// 按请求次数变响应的 adapter:前 [busyTimes] 次回 409,之后回 SSE 200(turn_done)。
/// http_mock_adapter 不支持同一路由按次序列化响应,故手写。
class _SeqAdapter implements HttpClientAdapter {
  _SeqAdapter(this.busyTimes);
  final int busyTimes;
  int calls = 0;

  @override
  Future<ResponseBody> fetch(RequestOptions options,
      Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async {
    calls++;
    if (calls <= busyTimes) {
      return ResponseBody.fromString(
        '{"detail":"session is busy"}',
        409,
        headers: {
          Headers.contentTypeHeader: ['application/json'],
        },
      );
    }
    return ResponseBody.fromString(
      'data: {"type":"turn_done","usage":{"input_tokens":1,"output_tokens":1},'
      '"message_ids":[],"stop_reason":"end_turn"}\n\n',
      200,
      headers: {
        Headers.contentTypeHeader: ['text/event-stream'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

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

  test('sendTurn:409 两次后锁释放 → 自动重试成功产出事件流', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    final adapter = _SeqAdapter(2);
    dio.httpClientAdapter = adapter;
    final events = await ChatRepository(dio)
        .sendTurn('s1', 'hi', retryDelay: Duration.zero)
        .toList();
    expect(adapter.calls, 3); // 409×2 + 成功 1
    expect(events.whereType<TurnDoneEvent>().length, 1);
  });

  test('sendTurn:持续 409 → 重试 5 次后抛 DioException', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    final adapter = _SeqAdapter(99);
    dio.httpClientAdapter = adapter;
    await expectLater(
      ChatRepository(dio).sendTurn('s1', 'hi', retryDelay: Duration.zero).toList(),
      throwsA(isA<DioException>()),
    );
    expect(adapter.calls, 5); // 首发 + 4 次重试
  });

  test('compactSession POST + 解析 compacted', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onPost(
      '/sessions/s1/compact',
      (s) => s.reply(200, {'compacted': true}),
    );
    expect(await ChatRepository(dio).compactSession('s1'), isTrue);
  });

  test('TurnEvent.fromJson 解析 compacting 事件', () {
    expect(TurnEvent.fromJson(jsonDecode('{"type":"compacting"}')),
        isA<CompactingEvent>());
  });
}
