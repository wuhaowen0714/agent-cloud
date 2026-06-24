from __future__ import annotations

import json

import grpc
from agent_cloud_common import (
    SubagentDone,
    SubagentStarted,
    TextDelta,
    ThinkingDelta,
    ToolCallProgress,
    ToolCallStarted,
    ToolResultEvent,
)

_RECOVERABLE = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.INTERNAL,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    # 上下文超窗:后端已 force-compact,重试通常就能装下 → 标记可恢复,提示用户重试。
    grpc.StatusCode.RESOURCE_EXHAUSTED,
}


def turn_event_to_sse(event, subagent_id: str = "") -> dict:
    """把流式回合事件(非 TurnDone)映射成前端 SSE JSON。subagent_id 非空时附在每个事件上
    (前端按它把子 agent 的事件分组渲染)。TurnDone 由端点单独处理。"""
    d = _event_to_sse_dict(event)
    if subagent_id:
        d["subagent_id"] = subagent_id
    return d


def _event_to_sse_dict(event) -> dict:
    if isinstance(event, TextDelta):
        return {"type": "text_delta", "text": event.text}
    if isinstance(event, ThinkingDelta):
        return {"type": "thinking_delta", "text": event.text}
    if isinstance(event, ToolCallProgress):
        return {
            "type": "tool_call_progress",
            "call_id": event.call_id,
            "tool": event.name,
            "args_chars": event.args_chars,
            "lines": event.lines,
            "path": event.path_hint,
        }
    if isinstance(event, ToolCallStarted):
        return {
            "type": "tool_call_start",
            "call_id": event.call_id,
            "tool": event.name,
            "args": event.arguments,
        }
    if isinstance(event, ToolResultEvent):
        return {
            "type": "tool_result",
            "call_id": event.call_id,
            "result": event.content,
            "is_error": event.is_error,
        }
    if isinstance(event, SubagentStarted):
        return {
            "type": "subagent_started",
            "subagent_id": event.subagent_id,
            "description": event.description,
        }
    if isinstance(event, SubagentDone):
        return {"type": "subagent_done", "subagent_id": event.subagent_id, "ok": event.ok}
    raise ValueError(f"unmapped streaming event: {type(event).__name__}")


def error_sse(code: grpc.StatusCode) -> dict:
    recoverable = code in _RECOVERABLE
    message = (
        "the turn was interrupted, please retry" if recoverable else "the request was rejected"
    )
    return {"type": "error", "message": message, "recoverable": recoverable}


def format_sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"
