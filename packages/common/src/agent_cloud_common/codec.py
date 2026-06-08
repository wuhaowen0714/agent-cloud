from __future__ import annotations

import json

from agent_cloud.v1 import worker_pb2

from agent_cloud_common.events import (
    TextDelta,
    ThinkingDelta,
    ToolCallStarted,
    ToolResultEvent,
    TurnDone,
    TurnEvent,
)
from agent_cloud_common.types import Message, Role, ToolCall, ToolResult, Usage


def msg_to_proto(message: Message) -> worker_pb2.Msg:
    return worker_pb2.Msg(
        role=message.role.value,
        text=message.text,
        tool_calls=[
            worker_pb2.ToolCall(id=c.id, name=c.name, arguments_json=json.dumps(c.arguments))
            for c in message.tool_calls
        ],
        tool_results=[
            worker_pb2.ToolResult(call_id=r.call_id, content=r.content, is_error=r.is_error)
            for r in message.tool_results
        ],
    )


def _parse_tool_arguments(arguments_json: str) -> dict:
    parsed = json.loads(arguments_json or "{}")
    if not isinstance(parsed, dict):
        raise ValueError(
            f"tool call arguments must be a JSON object, got {type(parsed).__name__}"
        )
    return parsed


def msg_from_proto(proto: worker_pb2.Msg) -> Message:
    return Message(
        role=Role(proto.role),
        text=proto.text,
        tool_calls=[
            ToolCall(id=c.id, name=c.name, arguments=_parse_tool_arguments(c.arguments_json))
            for c in proto.tool_calls
        ],
        tool_results=[
            ToolResult(call_id=r.call_id, content=r.content, is_error=r.is_error)
            for r in proto.tool_results
        ],
    )


def turn_event_to_proto(event: TurnEvent) -> worker_pb2.TurnEvent:
    if isinstance(event, TextDelta):
        return worker_pb2.TurnEvent(text_delta=worker_pb2.TextDelta(text=event.text))
    if isinstance(event, ThinkingDelta):
        return worker_pb2.TurnEvent(thinking_delta=worker_pb2.ThinkingDelta(text=event.text))
    if isinstance(event, ToolCallStarted):
        return worker_pb2.TurnEvent(
            tool_call_started=worker_pb2.ToolCallStarted(
                call_id=event.call_id, name=event.name,
                arguments_json=json.dumps(event.arguments),
            )
        )
    if isinstance(event, ToolResultEvent):
        return worker_pb2.TurnEvent(
            tool_result=worker_pb2.ToolResultEvent(
                call_id=event.call_id, content=event.content, is_error=event.is_error
            )
        )
    if isinstance(event, TurnDone):
        return worker_pb2.TurnEvent(
            turn_done=worker_pb2.TurnDone(
                new_messages=[msg_to_proto(m) for m in event.new_messages],
                input_tokens=event.usage.input_tokens,
                output_tokens=event.usage.output_tokens,
                stop_reason=event.stop_reason,
                context_tokens=event.context_tokens,
            )
        )
    raise ValueError(f"unknown turn event type: {type(event).__name__}")


def turn_event_from_proto(proto: worker_pb2.TurnEvent) -> TurnEvent:
    which = proto.WhichOneof("event")
    if which == "text_delta":
        return TextDelta(text=proto.text_delta.text)
    if which == "thinking_delta":
        return ThinkingDelta(text=proto.thinking_delta.text)
    if which == "tool_call_started":
        t = proto.tool_call_started
        return ToolCallStarted(
            call_id=t.call_id, name=t.name, arguments=json.loads(t.arguments_json or "{}")
        )
    if which == "tool_result":
        t = proto.tool_result
        return ToolResultEvent(call_id=t.call_id, content=t.content, is_error=t.is_error)
    if which == "turn_done":
        t = proto.turn_done
        return TurnDone(
            new_messages=[msg_from_proto(m) for m in t.new_messages],
            usage=Usage(input_tokens=t.input_tokens, output_tokens=t.output_tokens),
            stop_reason=t.stop_reason,
            context_tokens=t.context_tokens,
        )
    raise ValueError(f"empty or unknown TurnEvent oneof: {which!r}")
