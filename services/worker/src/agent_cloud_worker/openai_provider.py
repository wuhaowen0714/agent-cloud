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
# 其它兼容端点常只在 message 里写。markers 只保留**高度专指上下文窗口**的词:像
# "too long"/"reduce the length" 这类宽词会把"某参数过长"之类无关 400 也误判成超窗,
# 进而让后端误触发压缩(压缩抖动)。宁可漏报(退化为普通 INTERNAL,回合失败)也不假阳性。
_CONTEXT_LEN_MARKERS = (
    "context length",
    "maximum context",
    "context window",
    "context_length_exceeded",
)
_CONTEXT_LEN_CODE = "context_length_exceeded"


def _is_context_window_error(exc: Exception) -> bool:
    if not isinstance(exc, openai.BadRequestError):
        return False
    # 真实的 openai.BadRequestError 把上游文案/错误码嵌在 .body 的 error 子对象里;
    # .code/.message 在带结构化 body 时往往拿不到(.code=None、.message 仅是 "Error code: 400")。
    # 不同兼容端点/SDK 版本填充位置不一,故从 .code、.body(含 error 子对象)、str(exc) 全都收集。
    codes: list[str] = []
    texts: list[str] = [str(exc)]
    if code := getattr(exc, "code", None):
        codes.append(str(code))
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        for key in ("code", "type"):
            if err.get(key):
                codes.append(str(err[key]))
        if err.get("message"):
            texts.append(str(err["message"]))
    if _CONTEXT_LEN_CODE in codes:
        return True
    text = " ".join(texts).lower()
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


def _loads_or_empty(raw: str) -> dict:
    """工具参数解析:残缺/非法 JSON(典型:被 finish_reason=length 掐断)降级为 {},
    绝不让一次截断把整个请求炸成 INTERNAL(那会触发后端对确定性失败的重试风暴)。"""
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


def message_from_openai(om) -> Message:
    """OpenAI 响应 message → 领域 Message(assistant)。

    捕获 reasoning_content(思考模式端点),以便回合内后续请求把它回传(DeepSeek 等要求)。
    """
    tool_calls = [
        ToolCall(
            id=tc.id,
            name=tc.function.name,
            arguments=_loads_or_empty(tc.function.arguments),
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
        finish: str | None = None

        async for chunk in stream:
            if chunk.usage is not None:
                usage = Usage(
                    input_tokens=chunk.usage.prompt_tokens,
                    output_tokens=chunk.usage.completion_tokens,
                )
            if not chunk.choices:
                continue
            if chunk.choices[0].finish_reason:
                finish = chunk.choices[0].finish_reason
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

        # 组装 tool_calls:参数 JSON 解析失败(典型:被 length 掐断)的 call 降级为
        # arguments={} 并记入 truncated_call_ids,由 loop 跳过执行、回灌修复性错误;
        # id 分片可能还没到就被掐断,合成稳定 id 以保证 tool 结果能按 call_id 应答。
        tool_calls: list[ToolCall] = []
        truncated_call_ids: set[str] = set()
        for index, s in sorted(tool_acc.items()):
            call_id = s["id"] or f"truncated-{index}"
            try:
                arguments = json.loads(s["args"] or "{}")
            except json.JSONDecodeError:
                arguments = {}
                truncated_call_ids.add(call_id)
            tool_calls.append(ToolCall(id=call_id, name=s["name"], arguments=arguments))
        message = Message(
            role=Role.ASSISTANT,
            text="".join(text_parts),
            tool_calls=tool_calls,
            reasoning="".join(reasoning_parts),
        )
        yield ProviderCompleted(
            message=message,
            usage=usage,
            length_truncated=finish == "length",
            truncated_call_ids=truncated_call_ids,
        )
