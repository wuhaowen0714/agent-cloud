from __future__ import annotations

import json

from agent_cloud.v1 import worker_pb2

from agent_cloud_common.types import Message, Role, ToolCall, ToolResult


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
