from __future__ import annotations

from typing import Protocol

from agent_cloud_common import CompletionRequest, CompletionResult


class Provider(Protocol):
    async def complete(self, request: CompletionRequest) -> CompletionResult: ...


class FakeProvider:
    """脚本化 provider:按顺序返回预设的 CompletionResult。用于确定性测试 agent-loop。"""

    def __init__(self, scripted: list[CompletionResult]) -> None:
        self._scripted = list(scripted)
        self._index = 0

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        if self._index >= len(self._scripted):
            raise IndexError(f"FakeProvider script exhausted after {len(self._scripted)} calls")
        result = self._scripted[self._index]
        self._index += 1
        return result
