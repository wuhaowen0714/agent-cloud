from __future__ import annotations

import json

import grpc
from agent_cloud_common import TextDelta, ThinkingDelta, ToolCallStarted, ToolResultEvent

_RECOVERABLE = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.INTERNAL,
    grpc.StatusCode.DEADLINE_EXCEEDED,
}


def turn_event_to_sse(event) -> dict:
    """把流式回合事件(非 TurnDone)映射成前端 SSE JSON。TurnDone 由端点单独处理。"""
    if isinstance(event, TextDelta):
        return {"type": "text_delta", "text": event.text}
    if isinstance(event, ThinkingDelta):
        return {"type": "thinking_delta", "text": event.text}
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
    raise ValueError(f"unmapped streaming event: {type(event).__name__}")


def error_sse(code: grpc.StatusCode) -> dict:
    recoverable = code in _RECOVERABLE
    message = (
        "the turn was interrupted, please retry" if recoverable else "the request was rejected"
    )
    return {"type": "error", "message": message, "recoverable": recoverable}


def format_sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"
