from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

from agent_cloud_common import CompletionRequest, CompletionResult, Message, Usage


class ContextWindowExceeded(Exception):
    """provider 报告:请求超出模型上下文窗口(通常是上游 400)。

    与一般 provider 失败区分开,让 server 把它映射成 gRPC RESOURCE_EXHAUSTED,
    后端据此触发压缩并提示用户重试(spec §6/§8)。
    """


class CompletionBudgetExceeded(Exception):
    """provider 报告:配置的单次输出预算(request_max_tokens)自身放不进模型窗口。

    与 ContextWindowExceeded 必须区分:压缩历史只能缩小 prompt,救不了「completion
    预算 ≥ 窗口」的 400——若误判成超窗,后端会陷入注定无效的 force_compact 重试螺旋
    (小窗口 BYO 模型配置即砖)。server 把它映射成 FAILED_PRECONDITION(配置错误)。
    """


class Provider(Protocol):
    async def complete(self, request: CompletionRequest) -> CompletionResult: ...


# ---- provider 级流式事件 ----
@dataclass
class ProviderTextDelta:
    text: str


@dataclass
class ProviderThinkingDelta:
    text: str


@dataclass
class ProviderToolCallProgress:
    """LLM 正在生成某工具调用的参数(分片累积中,节流发射;不含内容)。"""

    call_id: str
    name: str
    args_chars: int
    lines: int
    path_hint: str


@dataclass
class ProviderCompleted:
    message: Message
    usage: Usage
    # finish_reason == "length":本次输出被单次 token 上限掐断(文本截断 → loop 上抛
    # stop_reason="length";若同时有残缺工具调用,见 truncated_call_ids)。
    length_truncated: bool = False
    # 参数 JSON 解析失败(几乎总是被 length 掐断)的 call id:arguments 已降级为 {},
    # loop 对这些 call 跳过执行、回灌修复性错误,让模型在回合内自行重试小块写入。
    truncated_call_ids: set[str] = field(default_factory=set)


ProviderEvent = (
    ProviderTextDelta | ProviderThinkingDelta | ProviderToolCallProgress | ProviderCompleted
)


class StreamingProvider(Protocol):
    async def stream(self, request: CompletionRequest) -> AsyncIterator[ProviderEvent]: ...


class FakeProvider:
    """脚本化 provider:按顺序返回预设的 CompletionResult。同时支持一元 complete 与流式 stream。"""

    def __init__(self, scripted: list[CompletionResult]) -> None:
        self._scripted = list(scripted)
        self._index = 0

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        if self._index >= len(self._scripted):
            raise IndexError(f"FakeProvider script exhausted after {len(self._scripted)} calls")
        result = self._scripted[self._index]
        self._index += 1
        return result

    async def stream(self, request: CompletionRequest) -> AsyncIterator[ProviderEvent]:
        if self._index >= len(self._scripted):
            raise IndexError(f"FakeProvider script exhausted after {len(self._scripted)} calls")
        result = self._scripted[self._index]
        self._index += 1
        if result.message.text:
            yield ProviderTextDelta(text=result.message.text)
        yield ProviderCompleted(message=result.message, usage=result.usage)
