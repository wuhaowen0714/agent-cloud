import 'dart:async'; // unawaited:队列自动续发不阻塞收尾
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../auth/auth_controller.dart'; // dioProvider
import '../../models/block.dart';
import '../../models/turn_event.dart';
import 'blocks.dart';
import 'chat_repository.dart';
import 'client_actions.dart';
import '../sessions/sessions_controller.dart'; // sessionsControllerProvider:刷新拿即时标题

enum ChatStatus { loading, idle, streaming, error }

/// 排队待发的消息(content 已含技能/附件 marker,images 为已上传的工作区相对路径)。
typedef QueuedMessage = ({String content, List<String> images});

class ChatState {
  final List<Turn> turns; // 历史回合
  final List<Block> live; // 当前流式回合的 blocks
  final String liveUser; // 当前回合的用户消息(气泡显示)
  final List<String> liveUserImages; // 当前回合用户发的图(工作区相对路径)
  final ChatStatus status;
  final String? error;
  final String? failedMessage; // 发起失败的消息(可重试)
  final bool compacting; // 回合前压缩进行中(「正在生成」文案切换为「正在压缩上下文」)
  final List<QueuedMessage> queued; // 生成中排队的消息:回合正常结束后依次自动发出

  const ChatState({
    this.turns = const [],
    this.live = const [],
    this.liveUser = '',
    this.liveUserImages = const [],
    this.status = ChatStatus.loading,
    this.error,
    this.failedMessage,
    this.compacting = false,
    this.queued = const [],
  });

  ChatState copyWith({
    List<Turn>? turns,
    List<Block>? live,
    String? liveUser,
    List<String>? liveUserImages,
    ChatStatus? status,
    String? error,
    String? failedMessage,
    bool clearFailed = false,
    bool? compacting,
    List<QueuedMessage>? queued,
  }) =>
      ChatState(
        turns: turns ?? this.turns,
        live: live ?? this.live,
        liveUser: liveUser ?? this.liveUser,
        liveUserImages: liveUserImages ?? this.liveUserImages,
        status: status ?? this.status,
        error: error ?? this.error,
        failedMessage:
            clearFailed ? null : (failedMessage ?? this.failedMessage),
        compacting: compacting ?? this.compacting,
        queued: queued ?? this.queued,
      );
}

class ChatController extends FamilyNotifier<ChatState, String> {
  static const _storage = FlutterSecureStorage(); // 队列持久化(app 被杀不丢排队消息)
  late final ChatRepository _repo;
  late final String _sid;
  CancelToken? _cancel;
  bool _resuming = false; // resume 在途守卫:回前台可能连续触发,只允许一条 resume 流
  final Set<String> _execedClientCalls = {}; // 已执行的客户端动作 call_id(去重防 resume 重放)

  @override
  ChatState build(String sessionId) {
    _sid = sessionId;
    _repo = ChatRepository(ref.read(dioProvider));
    ref.onDispose(() => _cancel?.cancel());
    _loadHistory();
    unawaited(_restoreQueue()); // 恢复上次未发完的排队消息(空闲则自动续发)
    return const ChatState(status: ChatStatus.loading);
  }

  Future<void> _loadHistory() async {
    try {
      final msgs = await _repo.history(_sid);
      state = state.copyWith(
          turns: messagesToTurns(msgs), status: ChatStatus.idle);
      _tryResume(); // 进会话时若有进行中回合,续看
    } catch (e) {
      state = state.copyWith(status: ChatStatus.error, error: '$e');
    }
  }

  /// 发消息:发起失败 → 可重试;已发起后中途断 → 由 retryResume() 走 resume。
  /// 回合进行中调用 = 排队(对标 Claude Code):当前回合正常结束后依次自动发出。
  Future<void> send(String content, {List<String> images = const []}) async {
    if (state.status == ChatStatus.streaming) {
      state = state.copyWith(
          queued: [...state.queued, (content: content, images: images)]);
      unawaited(_persistQueue());
      return;
    }
    final wasFirst = state.turns.isEmpty; // 首回合:后端首问即生成标题,发完轮询刷出来
    state = state.copyWith(
        live: const [],
        liveUser: content,
        liveUserImages: images,
        status: ChatStatus.streaming,
        clearFailed: true);
    _cancel = CancelToken();
    if (wasFirst) _pollTitle(); // 不 await:与回合并行(后端在 user 消息落库后即时起名)
    try {
      await for (final e in _repo.sendTurn(_sid, content,
          images: images, cancel: _cancel)) {
        _feed(e);
      }
      await _finishTurn();
    } on DioException catch (err) {
      if (CancelToken.isCancel(err)) return; // 主动取消,不算失败
      state = state.copyWith(status: ChatStatus.idle, failedMessage: content);
    }
  }

  /// 重发发起失败的消息。
  Future<void> retry() async {
    final msg = state.failedMessage;
    if (msg != null) await send(msg);
  }

  /// 空闲且有排队消息 → 立即取队首发出(审查 M1:队列消费点原只在回合流收尾,覆盖不到
  /// 「切走再切回、回合已在后台结束」的场景;进入聊天页时调用本方法补上这个触发点)。
  void kickQueue() {
    if (state.status != ChatStatus.idle || state.queued.isEmpty) return;
    final next = state.queued.first;
    state = state.copyWith(queued: state.queued.sublist(1));
    unawaited(_persistQueue());
    unawaited(send(next.content, images: next.images));
  }

  /// 删除一条排队中的消息。
  void removeQueued(int index) {
    if (index < 0 || index >= state.queued.length) return;
    final next = [...state.queued]..removeAt(index);
    state = state.copyWith(queued: next);
    unawaited(_persistQueue());
  }

  /// 停止当前回合:清空排队(停止=止损,自动续发违背用户意图)→ 掐本地流 → 服务端取消
  /// (幂等 204)→ 刷历史收尾(半截回复未落库,user 消息保留,assemble 会剥未答 user)。
  Future<void> stopTurn() async {
    state = state.copyWith(queued: const []);
    unawaited(_persistQueue());
    _cancel?.cancel(); // 本地流先停:其 isCancel 分支静默返回,不再 feed/收尾
    try {
      await _repo.cancelTurn(_sid);
    } catch (_) {
      // 服务端取消失败(网络等):本地已停;若回合实际仍在跑,后续发消息由 409 重试等锁,
      // 或回前台 resume 对齐,不在此扩大失败面。
    }
    await _finishTurn();
  }

  /// 回到某条用户消息「之前」:后端删它及之后的消息,本地刷历史拿最新 turns;返回该消息文本
  /// 供页面回填输入框。失败(如 409 会话忙)抛给调用方提示。仅在非 streaming 时可调(页面已禁)。
  Future<String> rollback(String messageId) async {
    final text = await _repo.rollback(_sid, messageId);
    final msgs = await _repo.history(_sid);
    state = state.copyWith(
        turns: messagesToTurns(msgs), status: ChatStatus.idle);
    return text;
  }

  /// 从某条用户消息「之前」分叉新会话(原会话不变)。返回新会话 id 与该消息文本。
  Future<({String newSessionId, String userText})> fork(String messageId) =>
      _repo.fork(_sid, messageId);

  // 首回合标题:后端在 user 消息落库后即时生成(不等回答),这里轮询刷 sessions 直到拿到 title
  // (或到上限)——让 chat 顶栏 / 会话列表尽快显示标题,不必等回合结束。
  Future<void> _pollTitle() async {
    for (var i = 0; i < 8; i++) {
      await Future.delayed(const Duration(milliseconds: 1200));
      try {
        await ref.read(sessionsControllerProvider.notifier).refresh();
        final sessions =
            ref.read(sessionsControllerProvider).asData?.value ?? const [];
        final m = sessions.where((s) => s.id == _sid);
        if (m.isNotEmpty && (m.first.title?.isNotEmpty ?? false)) return;
      } catch (_) {
        return; // controller 已 dispose / 拉取失败 → 停
      }
    }
  }

  /// 断流后手动/自动续看进行中回合(GET resume)。
  Future<void> retryResume() => _tryResume();

  Future<void> _tryResume() async {
    if (_resuming) return; // 防重入:回前台连续切换/重复调用只跑一条 resume,避免自掐健康流
    _resuming = true;
    // 取消可能还半开卡着的旧 send 流(切后台前的 await-for 未结束),避免新旧两条流竞争状态
    // (旧流稍后抛 cancel → send 的 isCancel 分支静默返回,不污染状态)。注:即使旧流其实健康
    // 也会重连——宁可多一次 resume(后端支持续看),不可卡死。
    _cancel?.cancel();
    // 记录发起 resume 时刻的状态:204(无进行中回合)只对「发起时就卡在 streaming」的场景
    // 做漏收 turn_done 兜底。若发起时是 idle(正常进会话),GET 在飞期间用户可能已发起新回合
    // ——那时的 streaming 是新回合的,绝不能被 _finishTurn 强刷成 idle(误杀正在跑的回合)。
    final wasStreaming = state.status == ChatStatus.streaming;
    try {
      _cancel = CancelToken();
      final stream = await _repo.resumeTurn(_sid, cancel: _cancel);
      if (stream == null) {
        // 没有进行中回合:若发起时就卡在 streaming(典型:客户端动作工具把 app 切后台、漏收
        // turn_done,回合其实已在服务端跑完),刷历史拿最终结果并清掉"生成中"。
        if (wasStreaming && state.status == ChatStatus.streaming) {
          await _finishTurn();
        }
        // 确认无进行中回合后补踢队列:_restoreQueue 完成时状态常还是 loading(其内部
        // kickQueue 被拦),这里是进会话链路上「确定空闲」的最早触发点(幂等,空队列 no-op;
        // 状态非 idle——如飞行中新开的回合——内部自拦)。
        kickQueue();
        return;
      }
      state = state.copyWith(status: ChatStatus.streaming);
      await for (final e in stream) {
        _feed(e);
      }
      await _finishTurn();
    } on DioException catch (err) {
      if (CancelToken.isCancel(err)) return;
      state = state.copyWith(status: ChatStatus.idle);
    } finally {
      _resuming = false;
    }
  }

  void _feed(TurnEvent e) {
    // 回合前压缩:compacting 事件置位(「正在生成」切「正在压缩上下文」);压缩结束后的
    // 首个真实回合事件到达即复位。
    if (state.compacting && e is! CompactingEvent) {
      state = state.copyWith(compacting: false);
    }
    switch (e) {
      case CompactingEvent():
        state = state.copyWith(compacting: true);
      case SubagentStarted(:final subagentId, :final description, :final prompt):
        state = state.copyWith(
            live: startSubagent(state.live, subagentId, description, prompt));
      case SubagentDone(:final subagentId, :final ok):
        state =
            state.copyWith(live: finishSubagent(state.live, subagentId, ok));
      case ResetEvent():
        state = state.copyWith(live: const []);
      case TurnDoneEvent():
        break; // 收尾在 _finishTurn
      default:
        // 客户端动作工具(set_alarm/add_calendar_event):主 agent 的 tool_call 在设备本地
        // 执行系统 Intent。call_id 去重 —— resume 重放同一事件时不重复设闹钟/加日程。
        if (e is ToolCallStart &&
            e.subagentId == null &&
            kClientActionTools.contains(e.tool) &&
            _execedClientCalls.add(e.callId)) {
          handleClientToolCall(e.tool, e.args);
        }
        final sid = _subagentId(e);
        state = state.copyWith(
            live: sid != null
                ? appendToSubagent(state.live, sid, e)
                : applyEvent(state.live, e));
    }
  }

  String? _subagentId(TurnEvent e) => switch (e) {
        TextDelta(:final subagentId) => subagentId,
        ThinkingDelta(:final subagentId) => subagentId,
        ToolCallStart(:final subagentId) => subagentId,
        ToolResultDelta(:final subagentId) => subagentId,
        _ => null,
      };

  /// 回合收尾:刷历史(拿落库的最终结果)+ 清 live;有排队消息则取队首自动续发。
  Future<void> _finishTurn() async {
    try {
      final msgs = await _repo.history(_sid);
      state = state.copyWith(
          turns: messagesToTurns(msgs),
          live: const [],
          liveUser: '',
          liveUserImages: const [],
          status: ChatStatus.idle,
          compacting: false);
      if (state.queued.isNotEmpty) {
        final next = state.queued.first;
        state = state.copyWith(queued: state.queued.sublist(1));
        unawaited(_persistQueue());
        // 不 await:收尾归收尾,续发是新回合(send 内部 streaming 守卫防竞态重入)。
        unawaited(send(next.content, images: next.images));
      }
    } catch (_) {
      // 刷历史失败(网络抖动):只收尾状态,不自动续发(大概率也会失败,留给用户手动)。
      state = state.copyWith(status: ChatStatus.idle, compacting: false);
    }
  }

  // ── 队列持久化:app 被杀/重启不丢排队消息(按会话一个 key;secure_storage 现成零新依赖)──

  Future<void> _persistQueue() async {
    try {
      if (state.queued.isEmpty) {
        await _storage.delete(key: 'queue.$_sid');
      } else {
        await _storage.write(
          key: 'queue.$_sid',
          value: jsonEncode([
            for (final q in state.queued)
              {'content': q.content, 'images': q.images},
          ]),
        );
      }
    } catch (_) {
      // 存储不可用(极少数 ROM keystore 抽风):队列仍在内存,仅重启后丢,不影响当前功能
    }
  }

  Future<void> _restoreQueue() async {
    try {
      final raw = await _storage.read(key: 'queue.$_sid');
      if (raw == null) return;
      final list = jsonDecode(raw);
      if (list is! List) return;
      final restored = <QueuedMessage>[
        for (final e in list)
          if (e is Map && e['content'] is String)
            (
              content: e['content'] as String,
              images: [
                for (final i in (e['images'] as List? ?? const []))
                  if (i is String) i,
              ],
            ),
      ];
      if (restored.isEmpty) return;
      // 追加而非覆盖:恢复期间用户可能已排了新消息(先到先发,恢复的更早、放前面)。
      state = state.copyWith(queued: [...restored, ...state.queued]);
      unawaited(_persistQueue()); // 合并结果落盘:防「恢复窗口内又入队」交错覆盖丢恢复项
      kickQueue(); // 空闲则立即续发(loading/streaming 时内部自拦,回合收尾会再消费)
    } catch (_) {
      // 坏数据/存储异常:按无持久化处理,绝不影响进会话
    }
  }
}

final chatControllerProvider =
    NotifierProvider.family<ChatController, ChatState, String>(
        ChatController.new);
