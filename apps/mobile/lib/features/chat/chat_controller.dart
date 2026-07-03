import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../auth/auth_controller.dart'; // dioProvider
import '../../models/block.dart';
import '../../models/turn_event.dart';
import 'blocks.dart';
import 'chat_repository.dart';
import 'client_actions.dart';
import '../sessions/sessions_controller.dart'; // sessionsControllerProvider:刷新拿即时标题

enum ChatStatus { loading, idle, streaming, error }

class ChatState {
  final List<Turn> turns; // 历史回合
  final List<Block> live; // 当前流式回合的 blocks
  final String liveUser; // 当前回合的用户消息(气泡显示)
  final List<String> liveUserImages; // 当前回合用户发的图(工作区相对路径)
  final ChatStatus status;
  final String? error;
  final String? failedMessage; // 发起失败的消息(可重试)
  final bool compacting; // 回合前压缩进行中(「正在生成」文案切换为「正在压缩上下文」)

  const ChatState({
    this.turns = const [],
    this.live = const [],
    this.liveUser = '',
    this.liveUserImages = const [],
    this.status = ChatStatus.loading,
    this.error,
    this.failedMessage,
    this.compacting = false,
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
      );
}

class ChatController extends FamilyNotifier<ChatState, String> {
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
  Future<void> send(String content, {List<String> images = const []}) async {
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
    try {
      _cancel = CancelToken();
      final stream = await _repo.resumeTurn(_sid, cancel: _cancel);
      if (stream == null) {
        // 没有进行中回合:若本地仍卡在 streaming(典型:客户端动作工具把 app 切后台、漏收了
        // turn_done,而回合其实已在服务端跑完),刷历史拿最终结果并清掉"生成中";否则(正常
        // 进会话)无需动作。
        if (state.status == ChatStatus.streaming) await _finishTurn();
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

  /// 回合收尾:刷历史(拿落库的最终结果)+ 清 live。
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
    } catch (_) {
      state = state.copyWith(status: ChatStatus.idle, compacting: false);
    }
  }
}

final chatControllerProvider =
    NotifierProvider.family<ChatController, ChatState, String>(
        ChatController.new);
