import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:agent_cloud_mobile/features/auth/auth_controller.dart';
import 'package:agent_cloud_mobile/features/chat/chat_controller.dart';

/// controller 级测试(真实 async,非 widget fake clock——后者与「永不关闭的 SSE 流 +
/// 标题轮询 timer」互斥)。按路由分发的可控 adapter:POST turn/stream 返回可手动推进/
/// 关闭的流,精确控制「回合进行中 / 回合结束」;记录 cancel 与每次 POST body。
class _RouterAdapter implements HttpClientAdapter {
  final List<StreamController<Uint8List>> turnStreams = [];
  final List<String> turnBodies = [];
  int cancelCalls = 0;

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(RequestOptions options,
      Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async {
    final path = options.path;
    if (options.method == 'POST' && path.endsWith('/turn/cancel')) {
      cancelCalls++;
      return ResponseBody.fromString('', 204);
    }
    if (options.method == 'POST' && path.endsWith('/turn/stream')) {
      turnBodies.add(jsonEncode(options.data));
      final ctrl = StreamController<Uint8List>();
      turnStreams.add(ctrl);
      return ResponseBody(ctrl.stream, 200, headers: {
        Headers.contentTypeHeader: ['text/event-stream'],
      });
    }
    if (options.method == 'GET' && path.endsWith('/turn/stream')) {
      return ResponseBody.fromString('', 204); // resume:无进行中回合
    }
    if (options.method == 'GET' && path.endsWith('/messages')) {
      // 预置一条历史:turns 非空 → send 不触发首回合标题轮询(其 1200ms delay 拖慢测试)
      return ResponseBody.fromString(
          jsonEncode([
            {
              'id': 'm0',
              'seq': 0,
              'role': 'user',
              'content': {'text': '旧消息'},
            }
          ]),
          200,
          headers: {
            Headers.contentTypeHeader: ['application/json'],
          });
    }
    return ResponseBody.fromString('[]', 200, headers: {
      Headers.contentTypeHeader: ['application/json'],
    });
  }

  /// 结束第 i 个回合:推 turn_done + 关流。
  Future<void> finishTurn(int i) async {
    turnStreams[i].add(Uint8List.fromList(utf8.encode(
        'data: {"type":"turn_done","usage":{"input_tokens":1,"output_tokens":1},'
        '"message_ids":[],"stop_reason":"end_turn"}\n\n')));
    await turnStreams[i].close();
  }
}

Future<void> _until(bool Function() cond,
    {Duration timeout = const Duration(seconds: 15)}) async {
  final end = DateTime.now().add(timeout);
  while (!cond()) {
    if (DateTime.now().isAfter(end)) fail('条件超时未满足($timeout)');
    await Future.delayed(const Duration(milliseconds: 10));
  }
}

({ProviderContainer container, _RouterAdapter adapter}) _setup() {
  final adapter = _RouterAdapter();
  final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
  dio.httpClientAdapter = adapter;
  final container =
      ProviderContainer(overrides: [dioProvider.overrideWithValue(dio)]);
  return (container: container, adapter: adapter);
}

void main() {
  // 全文件统一初始化 binding + 空 storage mock:secure_storage 在无 binding 的纯 test 里
  // 行为未定义(不同顺序下抛/挂不一致),统一 mock 让持久化路径确定(读空、写内存)。
  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    FlutterSecureStorage.setMockInitialValues({});
  });

  test('streaming 中 send → 入队不发 POST;回合正常结束自动续发队首', () async {
    final (:container, :adapter) = _setup();
    addTearDown(container.dispose);
    ChatState st() => container.read(chatControllerProvider('s1'));
    final ctrl = container.read(chatControllerProvider('s1').notifier);
    await _until(() => st().status == ChatStatus.idle);

    unawaited(ctrl.send('第一条')); // 流挂着不关 → 停在 streaming
    await _until(() => adapter.turnBodies.length == 1);
    expect(st().status, ChatStatus.streaming);

    await ctrl.send('第二条'); // streaming 中 → 入队立即返回
    await ctrl.send('第三条');
    expect(st().queued.map((q) => q.content).toList(), ['第二条', '第三条']);
    expect(adapter.turnBodies.length, 1); // 未直发

    await adapter.finishTurn(0); // 第一回合结束 → 自动续发「第二条」
    await _until(() => adapter.turnBodies.length == 2);
    expect(adapter.turnBodies[1], contains('第二条'));
    await _until(() => st().queued.length == 1); // 队列弹出一条
    expect(st().queued.single.content, '第三条');

    await adapter.finishTurn(1); // 第二回合结束 → 续发「第三条」
    await _until(() => adapter.turnBodies.length == 3);
    expect(adapter.turnBodies[2], contains('第三条'));
    await _until(() => st().queued.isEmpty);
  });

  test('removeQueued 删指定条;越界安全', () async {
    final (:container, :adapter) = _setup();
    addTearDown(container.dispose);
    ChatState st() => container.read(chatControllerProvider('s1'));
    final ctrl = container.read(chatControllerProvider('s1').notifier);
    await _until(() => st().status == ChatStatus.idle);

    unawaited(ctrl.send('第一条'));
    await _until(() => adapter.turnBodies.length == 1);
    await ctrl.send('A');
    await ctrl.send('B');
    ctrl.removeQueued(0);
    expect(st().queued.single.content, 'B');
    ctrl.removeQueued(5); // 越界 no-op
    expect(st().queued.single.content, 'B');
  });

  test('stopTurn:清空队列 + 服务端 cancel + 收尾 idle,不自动续发', () async {
    final (:container, :adapter) = _setup();
    addTearDown(container.dispose);
    ChatState st() => container.read(chatControllerProvider('s1'));
    final ctrl = container.read(chatControllerProvider('s1').notifier);
    await _until(() => st().status == ChatStatus.idle);

    unawaited(ctrl.send('第一条'));
    await _until(() => adapter.turnBodies.length == 1);
    await ctrl.send('排队的'); // 入队
    expect(st().queued.length, 1);

    await ctrl.stopTurn();
    expect(adapter.cancelCalls, 1);
    expect(st().queued, isEmpty); // 停止 = 队列一并清
    expect(st().status, ChatStatus.idle);
    // 稍等确认不会冒出自动续发
    await Future.delayed(const Duration(milliseconds: 100));
    expect(adapter.turnBodies.length, 1);
  });

  test('队列持久化:重建 controller 恢复排队消息并空闲自动续发', () async {
    TestWidgetsFlutterBinding.ensureInitialized();
    // 预置持久化的队列(上次 app 被杀时留下的)
    FlutterSecureStorage.setMockInitialValues({
      'queue.s1': '[{"content":"复活的排队消息","images":[]}]',
    });
    final (:container, :adapter) = _setup();
    addTearDown(container.dispose);
    ChatState st() => container.read(chatControllerProvider('s1'));
    container.read(chatControllerProvider('s1').notifier); // 触发 build
    // 恢复后空闲 → kickQueue 自动把它发出去
    await _until(() => adapter.turnBodies.isNotEmpty);
    expect(adapter.turnBodies.first, contains('复活的排队消息'));
    await _until(() => st().queued.isEmpty);
  });

  test('入队即持久化:secure_storage 里能读到', () async {
    TestWidgetsFlutterBinding.ensureInitialized();
    FlutterSecureStorage.setMockInitialValues({});
    final (:container, :adapter) = _setup();
    addTearDown(container.dispose);
    ChatState st() => container.read(chatControllerProvider('s1'));
    final ctrl = container.read(chatControllerProvider('s1').notifier);
    await _until(() => st().status == ChatStatus.idle);

    unawaited(ctrl.send('第一条'));
    await _until(() => adapter.turnBodies.length == 1);
    await ctrl.send('排队的');
    // 持久化是 unawaited 异步写:轮询读到为止
    const storage = FlutterSecureStorage();
    final end = DateTime.now().add(const Duration(seconds: 5));
    String? raw;
    while (raw == null && DateTime.now().isBefore(end)) {
      raw = await storage.read(key: 'queue.s1');
      if (raw == null) await Future.delayed(const Duration(milliseconds: 10));
    }
    expect(raw, isNotNull);
    expect(raw, contains('排队的'));
  });
}
