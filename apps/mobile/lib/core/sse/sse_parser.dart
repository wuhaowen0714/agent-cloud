import 'dart:convert';
import 'dart:typed_data';
import '../../models/turn_event.dart';

/// 把 SSE 字节流解析成 TurnEvent 流(对标 web parseSSE)。
/// 格式:每个事件 `data: {json}` 行,事件间用空行(`\n\n`)分隔。跨 chunk 用 buffer 拼。
Stream<TurnEvent> parseSse(Stream<Uint8List> bytes) async* {
  var buffer = '';
  await for (final chunk in bytes) {
    buffer += utf8.decode(chunk, allowMalformed: true);
    while (true) {
      final i = buffer.indexOf('\n\n');
      if (i == -1) break;
      final raw = buffer.substring(0, i);
      buffer = buffer.substring(i + 2);
      for (final line in raw.split('\n')) {
        if (!line.startsWith('data:')) continue;
        final data = line.substring(5).trim();
        if (data.isEmpty) continue;
        try {
          yield TurnEvent.fromJson(jsonDecode(data) as Map<String, dynamic>);
        } catch (_) {
          // 忽略坏行,不中断流
        }
      }
    }
  }
}
