import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../auth/auth_controller.dart'; // dioProvider
import '../../models/block.dart';
import '../../models/turn_event.dart';
import 'blocks.dart';
import 'chat_repository.dart';

enum ChatStatus { loading, idle, streaming, error }

class ChatState {
  final List<Turn> turns; // 历史回合
  final List<Block> live; // 当前流式回合的 blocks
  final String liveUser; // 当前回合的用户消息(气泡显示)
  final ChatStatus status;
  final String? error;
  final String? failedMessage; // 发起失败的消息(可重试)

  const ChatState({
    this.turns = const [],
    this.live = const [],
    this.liveUser = '',
    this.status = ChatStatus.loading,
    this.error,
    this.failedMessage,
  });

  ChatState copyWith({
    List<Turn>? turns,
    List<Block>? live,
    String? liveUser,
    ChatStatus? status,
    String? error,
    String? failedMessage,
    bool clearFailed = false,
  }) =>
      ChatState(
        turns: turns ?? this.turns,
        live: live ?? this.live,
        liveUser: liveUser ?? this.liveUser,
        status: status ?? this.status,
        error: error ?? this.error,
        failedMessage: clearFailed ? null : (failedMessage ?? this.failedMessage),
      );
}

class ChatController extends FamilyNotifier<ChatState, String> {
  late final ChatRepository _repo;
  late final String _sid;
  CancelToken? _cancel;

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
    state = state.copyWith(
        live: const [],
        liveUser: content,
        status: ChatStatus.streaming,
        clearFailed: true);
    _cancel = CancelToken();
    try {
      await for (final e in _repo.sendTurn(_sid, content,
          images: images, cancel: _cancel)) {
        _feed(e);
      }
      await _finishTurn();
    } on DioException catch (err) {
      if (CancelToken.isCancel(err)) return; // 主动取消,不算失败
      // 发起失败(连不上)→ 标记可重试;已发起后断流交给 resume(重进会话触发)。
      state = state.copyWith(status: ChatStatus.idle, failedMessage: content);
    }
  }

  /// 重发发起失败的消息。
  Future<void> retry() async {
    final msg = state.failedMessage;
    if (msg != null) await send(msg);
  }

  /// 断流后手动/自动续看进行中回合(GET resume)。
  Future<void> retryResume() => _tryResume();

  Future<void> _tryResume() async {
    try {
      _cancel = CancelToken();
      final stream = await _repo.resumeTurn(_sid, cancel: _cancel);
      if (stream == null) return; // 没有进行中回合
      state = state.copyWith(status: ChatStatus.streaming);
      await for (final e in stream) {
        _feed(e);
      }
      await _finishTurn();
    } on DioException catch (err) {
      if (CancelToken.isCancel(err)) return;
      state = state.copyWith(status: ChatStatus.idle);
    }
  }

  void _feed(TurnEvent e) {
    switch (e) {
      case SubagentStarted(:final subagentId, :final description, :final prompt):
        state = state.copyWith(
            live: startSubagent(state.live, subagentId, description, prompt));
      case SubagentDone(:final subagentId, :final ok):
        state = state.copyWith(live: finishSubagent(state.live, subagentId, ok));
      case ResetEvent():
        state = state.copyWith(live: const []);
      case TurnDoneEvent():
        break; // 收尾在 _finishTurn
      default:
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
          status: ChatStatus.idle);
    } catch (_) {
      state = state.copyWith(status: ChatStatus.idle);
    }
  }
}

final chatControllerProvider =
    NotifierProvider.family<ChatController, ChatState, String>(
        ChatController.new);
