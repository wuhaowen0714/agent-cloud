from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from agent_cloud_common import CompletionRequest, CompletionResult, Message, Usage


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
class ProviderCompleted:
    message: Message
    usage: Usage


ProviderEvent = ProviderTextDelta | ProviderThinkingDelta | ProviderCompleted


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
