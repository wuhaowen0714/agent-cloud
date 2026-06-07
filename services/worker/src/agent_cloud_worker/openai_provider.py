from __future__ import annotations

import json

from agent_cloud_common import (
    CompletionRequest,
    Message,
    Role,
    ToolCall,
    ToolSpec,
)


def to_openai_tools(tools: list[ToolSpec]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


def to_openai_messages(request: CompletionRequest) -> list[dict]:
    """领域消息 → OpenAI chat messages。tool 角色的每个 result 展开成一条 openai tool 消息。"""
    out: list[dict] = []
    if request.system:
        out.append({"role": "system", "content": request.system})
    for m in request.messages:
        if m.role == Role.USER:
            out.append({"role": "user", "content": m.text})
        elif m.role == Role.ASSISTANT:
            msg: dict = {"role": "assistant", "content": m.text or None}
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in m.tool_calls
                ]
            out.append(msg)
        elif m.role == Role.TOOL:
            for tr in m.tool_results:
                out.append({"role": "tool", "tool_call_id": tr.call_id, "content": tr.content})
    return out


def message_from_openai(om) -> Message:
    """OpenAI 响应 message → 领域 Message(assistant)。tool_call 参数始终 json.loads。"""
    tool_calls = [
        ToolCall(id=tc.id, name=tc.function.name, arguments=json.loads(tc.function.arguments or "{}"))
        for tc in (om.tool_calls or [])
    ]
    return Message(role=Role.ASSISTANT, text=om.content or "", tool_calls=tool_calls)
