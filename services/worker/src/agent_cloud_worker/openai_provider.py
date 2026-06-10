from __future__ import annotations

import json
import re
import secrets
import time
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
    CompletionBudgetExceeded,
    ContextWindowExceeded,
    ProviderCompleted,
    ProviderEvent,
    ProviderTextDelta,
    ProviderThinkingDelta,
    ProviderToolCallProgress,
)

# 工具参数生成进度:最小发射间隔(秒)。全局单计时器——流里 call 串行到达,
# 这同时也是整条流进度事件率的上界(回放缓冲量级随之有界)。
_PROGRESS_INTERVAL = 0.3
_monotonic = time.monotonic  # 测试可替换的时钟
_PATH_RE = re.compile(r'"path"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _sniff_path(args_prefix: str) -> str:
    """从累积中的参数 JSON 前缀提取 "path" 字段值(进度展示用)。

    JSON 字符串值内的引号必转义为 \\"——裸 "path" 键只可能是真实键位,不会误匹配
    content 文本。值要取到闭引号才命中(中途返回 "",下次再试)。
    """
    m = _PATH_RE.search(args_prefix)
    if not m:
        return ""
    raw = m.group(1)
    try:
        return json.loads(f'"{raw}"')  # 解码 \" \\ \uXXXX 等转义
    except json.JSONDecodeError:
        return raw

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


def _collect_error_fields(exc: Exception) -> tuple[list[str], str]:
    """从 BadRequestError 收集错误码与拼接文案(小写)。

    真实的 openai.BadRequestError 把上游文案/错误码嵌在 .body 的 error 子对象里;
    .code/.message 在带结构化 body 时往往拿不到(.code=None、.message 仅是 "Error code: 400")。
    不同兼容端点/SDK 版本填充位置不一,故从 .code、.body(含 error 子对象)、str(exc) 全都收集。
    """
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
    return codes, " ".join(texts).lower()


def _is_context_window_error(exc: Exception) -> bool:
    if not isinstance(exc, openai.BadRequestError):
        return False
    codes, text = _collect_error_fields(exc)
    if _CONTEXT_LEN_CODE in codes:
        return True
    return any(marker in text for marker in _CONTEXT_LEN_MARKERS)


# OpenAI/vLLM 超窗 400 的经典形态:
# "maximum context length is W tokens ... (N in the messages, M in the completion)"
_BUDGET_PATTERN = re.compile(
    r"maximum context length is (\d+)[\s\S]{0,200}?(\d+) in the messages"
    r"[\s\S]{0,80}?(\d+) in the completion"
)


def _is_completion_budget_error(exc: Exception) -> bool:
    """「completion 预算自身 ≥ 窗口」的 400:压缩历史(只能缩 N)永远救不了。

    只在能解析出三元组数字且 M ≥ W 时判真;解析不出来则保持既有超窗语义,宁可
    走压缩路径也不把真超窗误判成配置错误。"""
    if not isinstance(exc, openai.BadRequestError):
        return False
    _, text = _collect_error_fields(exc)
    m = _BUDGET_PATTERN.search(text)
    if not m:
        return False
    window, _messages, completion = (int(g) for g in m.groups())
    return completion >= window


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
            if _is_completion_budget_error(exc):  # 先于超窗判:其文案同样命中超窗 markers
                raise CompletionBudgetExceeded(str(exc)) from exc
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
            if _is_completion_budget_error(exc):  # 先于超窗判:其文案同样命中超窗 markers
                raise CompletionBudgetExceeded(str(exc)) from exc
            if _is_context_window_error(exc):
                raise ContextWindowExceeded(str(exc)) from exc
            raise

        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        # index -> {"id","name","args","path"};按 index 累积分片的 tool_call 参数
        tool_acc: dict[int, dict] = {}
        usage = Usage()
        finish: str | None = None
        last_progress = 0.0  # 上次进度发射时刻(_monotonic);0 → 首个参数分片立即发

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
                slot = tool_acc.setdefault(
                    tcd.index, {"id": "", "name": "", "args": "", "path": ""}
                )
                if tcd.id:
                    slot["id"] = tcd.id
                if tcd.function and tcd.function.name:
                    slot["name"] = tcd.function.name
                if tcd.function and tcd.function.arguments:
                    slot["args"] += tcd.function.arguments
                    now = _monotonic()
                    # 节流进度:id/name 已知(OpenAI 兼容流首分片即带)才发,否则是
                    # 无法与后续 ToolCallStarted 配对的孤儿。只发计数不发内容;
                    # 行数 = \n 转义数 + 1(字面 \\n 会误计,提示用途可接受)。
                    if slot["id"] and slot["name"] and now - last_progress >= _PROGRESS_INTERVAL:
                        if not slot["path"]:
                            slot["path"] = _sniff_path(slot["args"])
                        last_progress = now
                        yield ProviderToolCallProgress(
                            call_id=slot["id"],
                            name=slot["name"],
                            args_chars=len(slot["args"]),
                            lines=slot["args"].count("\\n") + 1,
                            path_hint=slot["path"],
                        )

        # 组装 tool_calls:参数 JSON 解析失败(典型:被 length 掐断)的 call 降级为
        # arguments={} 并记入 truncated_call_ids,由 loop 跳过执行、回灌修复性错误。
        # id 分片可能还没到就被掐断 → 合成 id(纯字母数字,兼容对 call_id 格式严格的端点)。
        tool_calls: list[ToolCall] = []
        truncated_call_ids: set[str] = set()
        last_index = max(tool_acc) if tool_acc else None
        for index, s in sorted(tool_acc.items()):
            call_id = s["id"] or f"trunc{index}{secrets.token_hex(3)}"
            try:
                arguments = json.loads(s["args"] or "{}")
            except json.JSONDecodeError:
                arguments = {}
                truncated_call_ids.add(call_id)
            # 被 length 掐断且末尾 call 的参数一个分片都没到:空 args 能"解析成功",
            # 但那是模型从未说完的调用——同样按截断处理,不能拿 {} 真执行。
            if finish == "length" and index == last_index and not s["args"]:
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
