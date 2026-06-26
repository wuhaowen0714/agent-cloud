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
      data: {'content': content, 'images': images, 'client': 'mobile'},
      // 兜底:流超 8min 无任何数据(连接层卡:网络半开/后端死)→ 抛 receiveTimeout 终止
      // "正在生成"而非永久转。8min > 后端单工具执行上限 360s,不误切正常长工具;worker 侧
      // 空转看门狗(~45s)是主防线,这里只兜 worker 管不到的连接层卡,转 error 后可重试。
      options: Options(
        responseType: ResponseType.stream,
        receiveTimeout: const Duration(minutes: 8),
      ),
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
        receiveTimeout: const Duration(minutes: 8), // 同 sendTurn:连接层卡兜底
      ),
      cancelToken: cancel,
    );
    // 仅 200 才是真正的回合事件流;204(无进行中回合)及任何 4xx(鉴权失败/会话不存在等,
    // validateStatus 放行了 <500)都返回 null,避免把错误响应体当 SSE 解析、静默吞成"回合正常结束"。
    if (r.statusCode != 200 || r.data == null) return null;
    return parseSse((r.data as ResponseBody).stream);
  }
}
