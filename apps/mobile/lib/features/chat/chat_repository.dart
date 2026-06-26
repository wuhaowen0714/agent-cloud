import 'package:dio/dio.dart';
import '../../core/sse/sse_parser.dart';
import '../../models/message.dart';
import '../../models/turn_event.dart';

class ChatRepository {
  ChatRepository(this._dio);
  final Dio _dio;

  /// 历史消息(按 seq 排序)。
  Future<List<Message>> history(String sessionId) async {
    final r = await _dio.get('/sessions/$sessionId/messages');
    return (r.data as List)
        .map((e) => Message.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 发起新回合:POST turn/stream(SSE)。返回事件流。
  Stream<TurnEvent> sendTurn(
    String sessionId,
    String content, {
    List<String> images = const [],
    CancelToken? cancel,
  }) async* {
    final r = await _dio.post(
      '/sessions/$sessionId/turn/stream',
      data: {'content': content, 'images': images},
      options: Options(responseType: ResponseType.stream),
      cancelToken: cancel,
    );
    yield* parseSse((r.data as ResponseBody).stream);
  }

  /// resume 续看进行中的回合:GET turn/stream。204 → null(没在跑)。
  Future<Stream<TurnEvent>?> resumeTurn(String sessionId,
      {CancelToken? cancel}) async {
    final r = await _dio.get(
      '/sessions/$sessionId/turn/stream',
      options: Options(
        responseType: ResponseType.stream,
        validateStatus: (s) => s != null && s < 500,
      ),
      cancelToken: cancel,
    );
    if (r.statusCode == 204) return null;
    return parseSse((r.data as ResponseBody).stream);
  }
}
