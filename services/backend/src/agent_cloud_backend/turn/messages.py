from __future__ import annotations

from agent_cloud_backend.models.message import Message as OrmMessage
from agent_cloud_common import Message as CommonMessage
from agent_cloud_common import Role, ToolCall, ToolResult


def orm_to_common(message: OrmMessage) -> CommonMessage:
    content = message.content or {}
    return CommonMessage(
        role=Role(message.role),
        text=content.get("text", ""),
        tool_calls=[ToolCall(**c) for c in content.get("tool_calls", [])],
        tool_results=[ToolResult(**r) for r in content.get("tool_results", [])],
    )


def common_to_content(message: CommonMessage) -> dict:
    return {
        "text": message.text,
        "tool_calls": [
            {"id": c.id, "name": c.name, "arguments": c.arguments} for c in message.tool_calls
        ],
        "tool_results": [
            {"call_id": r.call_id, "content": r.content, "is_error": r.is_error}
            for r in message.tool_results
        ],
    }
