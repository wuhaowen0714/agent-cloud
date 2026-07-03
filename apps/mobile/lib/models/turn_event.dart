/// SSE 回合事件(对标后端 turn_event_to_sse / web types.ts)。
sealed class TurnEvent {
  const TurnEvent();

  factory TurnEvent.fromJson(Map<String, dynamic> j) {
    final sid = j['subagent_id'] as String?;
    switch (j['type'] as String?) {
      case 'text_delta':
        return TextDelta(j['text'] as String? ?? '', sid);
      case 'thinking_delta':
        return ThinkingDelta(j['text'] as String? ?? '', sid);
      case 'tool_call_start':
        return ToolCallStart(
          j['call_id'] as String,
          j['tool'] as String,
          (j['args'] as Map?)?.cast<String, dynamic>() ?? const {},
          sid,
        );
      case 'tool_result':
        return ToolResultDelta(
          j['call_id'] as String,
          j['result'] as String? ?? '',
          j['is_error'] as bool? ?? false,
          sid,
        );
      case 'turn_done':
        return const TurnDoneEvent();
      case 'subagent_started':
        return SubagentStarted(
          j['subagent_id'] as String,
          j['description'] as String? ?? '',
          j['prompt'] as String? ?? '',
        );
      case 'subagent_done':
        return SubagentDone(
            j['subagent_id'] as String, j['ok'] as bool? ?? true);
      case 'reset':
        return const ResetEvent();
      case 'compacting':
        return const CompactingEvent(); // 回合前压缩进行中(上下文超阈值)
      case 'error':
        return ErrorEvent(j['message'] as String? ?? 'error');
      default:
        return const UnknownEvent();
    }
  }
}

class TextDelta extends TurnEvent {
  final String text;
  final String? subagentId;
  const TextDelta(this.text, this.subagentId);
}

class ThinkingDelta extends TurnEvent {
  final String text;
  final String? subagentId;
  const ThinkingDelta(this.text, this.subagentId);
}

class ToolCallStart extends TurnEvent {
  final String callId;
  final String tool;
  final Map<String, dynamic> args;
  final String? subagentId;
  const ToolCallStart(this.callId, this.tool, this.args, this.subagentId);
}

class ToolResultDelta extends TurnEvent {
  final String callId;
  final String result;
  final bool isError;
  final String? subagentId;
  const ToolResultDelta(this.callId, this.result, this.isError, this.subagentId);
}

class TurnDoneEvent extends TurnEvent {
  const TurnDoneEvent();
}

class SubagentStarted extends TurnEvent {
  final String subagentId;
  final String description;
  final String prompt;
  const SubagentStarted(this.subagentId, this.description, this.prompt);
}

class SubagentDone extends TurnEvent {
  final String subagentId;
  final bool ok;
  const SubagentDone(this.subagentId, this.ok);
}

class ResetEvent extends TurnEvent {
  const ResetEvent();
}

/// 回合前压缩进行中:上下文超阈值,后端先折叠历史再跑本回合(期间无别的事件)。
class CompactingEvent extends TurnEvent {
  const CompactingEvent();
}

class ErrorEvent extends TurnEvent {
  final String message;
  const ErrorEvent(this.message);
}

class UnknownEvent extends TurnEvent {
  const UnknownEvent();
}
