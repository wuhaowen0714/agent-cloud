from __future__ import annotations

import json
from collections.abc import AsyncIterator

from agent_cloud_common import (
    CompletionRequest,
    CompletionResult,
    Message,
    Role,
    ToolCall,
    ToolSpec,
    Usage,
)

from agent_cloud_worker.provider import (
    ProviderCompleted,
    ProviderEvent,
    ProviderTextDelta,
    ProviderThinkingDelta,
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
        ToolCall(
            id=tc.id,
            name=tc.function.name,
            arguments=json.loads(tc.function.arguments or "{}"),
        )
        for tc in (om.tool_calls or [])
    ]
    return Message(role=Role.ASSISTANT, text=om.content or "", tool_calls=tool_calls)


class OpenAIProvider:
    """OpenAI 兼容 chat completions 的 provider(注入 AsyncOpenAI 或兼容 client)。

    实现既有 Provider/StreamingProvider 协议(complete + stream)。client 由 factory
    用 base_url 覆盖构造,因此可对接任意 OpenAI 兼容端点。
    """

    def __init__(self, client, model: str, max_tokens: int) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    def _create_kwargs(self, request: CompletionRequest) -> dict:
        kwargs: dict = {
            "model": self._model,
            "messages": to_openai_messages(request),
            "max_tokens": self._max_tokens,
        }
        if request.tools:
            kwargs["tools"] = to_openai_tools(request.tools)
        return kwargs

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        resp = await self._client.chat.completions.create(**self._create_kwargs(request))
        message = message_from_openai(resp.choices[0].message)
        usage = Usage(
            input_tokens=resp.usage.prompt_tokens,
            output_tokens=resp.usage.completion_tokens,
        )
        return CompletionResult(message=message, usage=usage)

    async def stream(self, request: CompletionRequest) -> AsyncIterator[ProviderEvent]:
        kwargs = self._create_kwargs(request)
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}
        stream = await self._client.chat.completions.create(**kwargs)

        text_parts: list[str] = []
        # index -> {"id","name","args"};按 index 累积分片的 tool_call 参数
        tool_acc: dict[int, dict] = {}
        usage = Usage()

        async for chunk in stream:
            if chunk.usage is not None:
                usage = Usage(
                    input_tokens=chunk.usage.prompt_tokens,
                    output_tokens=chunk.usage.completion_tokens,
                )
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield ProviderThinkingDelta(text=reasoning)
            if delta.content:
                text_parts.append(delta.content)
                yield ProviderTextDelta(text=delta.content)
            for tcd in delta.tool_calls or []:
                slot = tool_acc.setdefault(tcd.index, {"id": "", "name": "", "args": ""})
                if tcd.id:
                    slot["id"] = tcd.id
                if tcd.function and tcd.function.name:
                    slot["name"] = tcd.function.name
                if tcd.function and tcd.function.arguments:
                    slot["args"] += tcd.function.arguments

        tool_calls = [
            ToolCall(id=s["id"], name=s["name"], arguments=json.loads(s["args"] or "{}"))
            for _, s in sorted(tool_acc.items())
        ]
        message = Message(role=Role.ASSISTANT, text="".join(text_parts), tool_calls=tool_calls)
        yield ProviderCompleted(message=message, usage=usage)
