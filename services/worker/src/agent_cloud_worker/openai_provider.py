from __future__ import annotations

import json
from collections.abc import AsyncIterator

import openai
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
    ContextWindowExceeded,
    ProviderCompleted,
    ProviderEvent,
    ProviderTextDelta,
    ProviderThinkingDelta,
)

# 上游对“超出上下文窗口”没有统一表示:OpenAI 用 code=context_length_exceeded,
# 其它兼容端点常只在 message 里写。两者都查,且仅针对 400(BadRequest)以免误伤别的错误。
_CONTEXT_LEN_MARKERS = (
    "context length",
    "maximum context",
    "context window",
    "too long",
    "reduce the length",
    "reduce your prompt",
)


def _is_context_window_error(exc: Exception) -> bool:
    if not isinstance(exc, openai.BadRequestError):
        return False
    if getattr(exc, "code", None) == "context_length_exceeded":
        return True
    text = str(getattr(exc, "message", "") or exc).lower()
    return any(marker in text for marker in _CONTEXT_LEN_MARKERS)


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
            # content 仅在有 tool_calls 时才可为 null;否则空文本必须是 ""(OpenAI 拒绝
            # 无 tool_calls 的 content=null),否则回放历史里的空 assistant 会 400。
            content = (m.text or None) if m.tool_calls else m.text
            msg: dict = {"role": "assistant", "content": content}
            # 思考模式端点(DeepSeek 等)要求把发起工具调用那轮的 reasoning_content 回传;
            # 非思考端点 m.reasoning 恒为 "",不会带这个字段,故对两者都安全。
            if m.reasoning:
                msg["reasoning_content"] = m.reasoning
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
                # OpenAI 的 tool 角色没有 is_error 字段,把失败标记折进 content,
                # 否则模型分不清工具成功还是失败。
                content = f"[tool error] {tr.content}" if tr.is_error else tr.content
                out.append({"role": "tool", "tool_call_id": tr.call_id, "content": content})
    return out


def message_from_openai(om) -> Message:
    """OpenAI 响应 message → 领域 Message(assistant)。tool_call 参数始终 json.loads。

    捕获 reasoning_content(思考模式端点),以便回合内后续请求把它回传(DeepSeek 等要求)。
    """
    tool_calls = [
        ToolCall(
            id=tc.id,
            name=tc.function.name,
            arguments=json.loads(tc.function.arguments or "{}"),
        )
        for tc in (om.tool_calls or [])
    ]
    reasoning = getattr(om, "reasoning_content", None) or ""
    return Message(
        role=Role.ASSISTANT, text=om.content or "", tool_calls=tool_calls, reasoning=reasoning
    )


class OpenAIProvider:
    """OpenAI 兼容 chat completions 的 provider(注入 AsyncOpenAI 或兼容 client)。

    实现既有 Provider/StreamingProvider 协议(complete + stream)。client 由 factory
    用 base_url 覆盖构造,因此可对接任意 OpenAI 兼容端点。
    """

    def __init__(
        self, client, model: str, max_tokens: int, max_tokens_param: str = "max_tokens"
    ) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._max_tokens_param = max_tokens_param

    def _create_kwargs(self, request: CompletionRequest) -> dict:
        kwargs: dict = {
            "model": self._model,
            "messages": to_openai_messages(request),
            self._max_tokens_param: self._max_tokens,
        }
        if request.tools:
            kwargs["tools"] = to_openai_tools(request.tools)
        return kwargs

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        try:
            resp = await self._client.chat.completions.create(**self._create_kwargs(request))
        except openai.BadRequestError as exc:
            if _is_context_window_error(exc):
                raise ContextWindowExceeded(str(exc)) from exc
            raise
        message = message_from_openai(resp.choices[0].message)
        # 部分 OpenAI 兼容端点非流式响应可能不带 usage;缺失按 0 计,不让成功的回合崩。
        u = resp.usage
        usage = Usage(
            input_tokens=u.prompt_tokens if u else 0,
            output_tokens=u.completion_tokens if u else 0,
        )
        return CompletionResult(message=message, usage=usage)

    async def stream(self, request: CompletionRequest) -> AsyncIterator[ProviderEvent]:
        kwargs = self._create_kwargs(request)
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}
        try:
            stream = await self._client.chat.completions.create(**kwargs)
        except openai.BadRequestError as exc:
            if _is_context_window_error(exc):
                raise ContextWindowExceeded(str(exc)) from exc
            raise

        text_parts: list[str] = []
        reasoning_parts: list[str] = []
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
                reasoning_parts.append(reasoning)
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
        message = Message(
            role=Role.ASSISTANT,
            text="".join(text_parts),
            tool_calls=tool_calls,
            reasoning="".join(reasoning_parts),
        )
        yield ProviderCompleted(message=message, usage=usage)
