# Plan 3a: 流式 agent 核心 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 agent 核心加流式能力:流式 `Provider`(`stream()` 产生 token deltas + 最终消息)、`run_turn_stream` 异步生成器(yield 回合事件:text_delta / tool_call / tool_result / turn_done)、流式 `FakeProvider`,以及共享的回合事件类型。纯库、可独立测试、无网络。

**Architecture:** 在 `packages/common` 加 `events.py`(回合事件 dataclass,3b 会映射成 proto、3c 会转 SSE)。worker 的 `provider.py` 加 provider 级流式事件 + `StreamingProvider` Protocol + `FakeProvider.stream`。`loop.py` 加 `run_turn_stream` 异步生成器:消费 `provider.stream` 转发文本增量、累积 assistant 消息、执行工具并 yield 工具事件,最后 yield `TurnDone`(携带 new_messages 供后端持久化)。**纯增量**:现有一元 `run_turn`/`Provider.complete` 保留(非流式路径/测试不动)。

**Tech Stack:** Python 3.12+、纯 stdlib(dataclasses/asyncio)、pytest + pytest-asyncio + ruff。**无网络/DB/Docker**——快速单元测试。

参考:spec `docs/superpowers/specs/2026-06-05-stateless-agent-cloud-design.md`(§7-② 流式事件、§8)。已合并:2a(`run_turn`/`Provider`/`FakeProvider`/`ToolExecutor`/`LocalToolExecutor`)、2c(common `codec`)。

## 范围

**做**:common 回合事件类型;worker provider 级流式事件 + `StreamingProvider` + `FakeProvider.stream`;`run_turn_stream` 异步生成器;单元测试。

**不做(Plan 3b/3c)**:worker 的流式 gRPC(server-streaming `RunTurnStream`)、后端 SSE、事件↔proto 映射。本计划的事件类型与 `run_turn_stream` 是 3b 的接缝。

## 事件模型

- **回合事件(common,worker→后端 的语义契约)**:`TextDelta`、`ThinkingDelta`、`ToolCallStarted`、`ToolResultEvent`、`TurnDone`(含 `new_messages`/`usage`/`stop_reason`)。
- **provider 级事件(worker 内部)**:`ProviderTextDelta`、`ProviderThinkingDelta`、`ProviderCompleted`(含完整 assistant `Message` + `Usage`)。provider 的 stream **必须**以恰好一个 `ProviderCompleted` 结束。

## File Structure

```
packages/common/src/agent_cloud_common/
  events.py              # TextDelta/ThinkingDelta/ToolCallStarted/ToolResultEvent/TurnDone + TurnEvent 联合
  __init__.py            # 导出回合事件
services/worker/src/agent_cloud_worker/
  provider.py            # +ProviderTextDelta/ThinkingDelta/Completed, +StreamingProvider, +FakeProvider.stream
  loop.py                # +run_turn_stream(...)
  __init__.py            # 导出 run_turn_stream + StreamingProvider + provider 事件
  tests/test_provider.py # +流式测试
  tests/test_loop.py     # +run_turn_stream 测试
```

---

### Task 0: 回合事件类型(common)

**Files:**
- Create: `packages/common/src/agent_cloud_common/events.py`
- Modify: `packages/common/src/agent_cloud_common/__init__.py`

> 纯 dataclass(只依赖 types),由 worker 测试覆盖。

- [ ] **Step 1: 写 events.py**

Create `packages/common/src/agent_cloud_common/events.py`:
```python
from __future__ import annotations

from dataclasses import dataclass

from agent_cloud_common.types import Message, Usage


@dataclass
class TextDelta:
    text: str


@dataclass
class ThinkingDelta:
    text: str


@dataclass
class ToolCallStarted:
    call_id: str
    name: str
    arguments: dict


@dataclass
class ToolResultEvent:
    call_id: str
    content: str
    is_error: bool


@dataclass
class TurnDone:
    new_messages: list[Message]
    usage: Usage
    stop_reason: str  # "end_turn" | "max_iterations"


TurnEvent = TextDelta | ThinkingDelta | ToolCallStarted | ToolResultEvent | TurnDone
```

- [ ] **Step 2: 导出**

Edit `packages/common/src/agent_cloud_common/__init__.py`: add
```python
from agent_cloud_common.events import (
    TextDelta,
    ThinkingDelta,
    ToolCallStarted,
    ToolResultEvent,
    TurnDone,
    TurnEvent,
)
```
and add those names to `__all__`.

- [ ] **Step 3: 冒烟**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run python -c "from agent_cloud_common import TextDelta, TurnDone; print(TextDelta(text='hi'))"`
Expected: 打印 `TextDelta(text='hi')`。

- [ ] **Step 4: 提交**

```bash
git add packages/common/src/agent_cloud_common/events.py packages/common/src/agent_cloud_common/__init__.py
git commit -m "feat(common): add streaming turn event types"
```

---

### Task 1: 流式 Provider(provider 事件 + StreamingProvider + FakeProvider.stream)

**Files:**
- Modify: `services/worker/src/agent_cloud_worker/provider.py`
- Test: `services/worker/tests/test_provider.py`

- [ ] **Step 1: 写失败测试(追加到 test_provider.py)**

Append to `services/worker/tests/test_provider.py`:
```python
from agent_cloud_common import CompletionRequest, Message, Role, ToolCall, Usage
from agent_cloud_worker.provider import (
    FakeProvider,
    ProviderCompleted,
    ProviderTextDelta,
)


def _completion(text: str) -> CompletionResult:
    return CompletionResult(
        message=Message(role=Role.ASSISTANT, text=text),
        usage=Usage(input_tokens=1, output_tokens=2),
    )


async def test_stream_yields_text_delta_then_completed():
    provider = FakeProvider([_completion("hi")])
    events = [e async for e in provider.stream(CompletionRequest(system="", messages=[], tools=[]))]
    assert isinstance(events[0], ProviderTextDelta) and events[0].text == "hi"
    assert isinstance(events[-1], ProviderCompleted)
    assert events[-1].message.text == "hi"
    assert events[-1].usage.output_tokens == 2


async def test_stream_tool_call_message_only_completed():
    provider = FakeProvider([CompletionResult(
        message=Message(role=Role.ASSISTANT,
                        tool_calls=[ToolCall(id="c1", name="bash", arguments={})]),
        usage=Usage())])
    events = [e async for e in provider.stream(CompletionRequest(system="", messages=[], tools=[]))]
    assert len(events) == 1 and isinstance(events[0], ProviderCompleted)
    assert events[0].message.tool_calls[0].name == "bash"
```
> Note: `CompletionResult` is already imported at the top of `test_provider.py` (from Plan 2a). If not, add `from agent_cloud_common import CompletionResult`.

- [ ] **Step 2: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_provider.py -v`
Expected: FAIL(`ImportError: cannot import name 'ProviderCompleted'`)。

- [ ] **Step 3: 实现流式 provider**

Edit `services/worker/src/agent_cloud_worker/provider.py` — replace its contents with:
```python
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
        result = self._scripted[self._index]  # 耗尽 -> IndexError
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
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_provider.py -v`
Expected: PASS(原有 2 + 新 2 = 4)。

- [ ] **Step 5: 提交**

```bash
git add services/worker/src/agent_cloud_worker/provider.py services/worker/tests/test_provider.py
git commit -m "feat(worker): add streaming Provider protocol and FakeProvider.stream"
```

---

### Task 2: run_turn_stream(流式回合)

**Files:**
- Modify: `services/worker/src/agent_cloud_worker/loop.py`
- Test: `services/worker/tests/test_loop.py`

- [ ] **Step 1: 写失败测试(追加到 test_loop.py)**

Append to `services/worker/tests/test_loop.py`:
```python
import pytest

from agent_cloud_common import TextDelta, ToolCallStarted, ToolResultEvent, TurnDone
from agent_cloud_worker.loop import run_turn_stream


async def test_stream_single_response_no_tools(tmp_path):
    provider = FakeProvider([_say("hello")])
    events = [
        e async for e in run_turn_stream(
            provider, _executor(tmp_path), system="", history=[], user_message="hi")
    ]
    assert isinstance(events[0], TextDelta) and events[0].text == "hello"
    assert isinstance(events[-1], TurnDone)
    assert events[-1].stop_reason == "end_turn"
    assert [m.role for m in events[-1].new_messages] == [Role.ASSISTANT]
    assert events[-1].usage.output_tokens == 5


async def test_stream_one_tool_round(tmp_path):
    provider = FakeProvider([
        _call("write_file", {"path": "o.txt", "content": "data"}),
        _say("done"),
    ])
    events = [
        e async for e in run_turn_stream(
            provider, _executor(tmp_path), system="", history=[], user_message="go")
    ]
    kinds = [type(e).__name__ for e in events]
    assert "ToolCallStarted" in kinds and "ToolResultEvent" in kinds
    started = next(e for e in events if isinstance(e, ToolCallStarted))
    assert started.name == "write_file"
    tool_res = next(e for e in events if isinstance(e, ToolResultEvent))
    assert tool_res.is_error is False
    assert isinstance(events[-1], TurnDone) and events[-1].stop_reason == "end_turn"
    assert (tmp_path / "o.txt").read_text() == "data"
    assert [m.role for m in events[-1].new_messages] == [Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]
    assert events[-1].usage.output_tokens == 10  # 两轮累加


async def test_stream_max_iterations(tmp_path):
    provider = FakeProvider([_call("bash", {"command": "echo x"}) for _ in range(5)])
    events = [
        e async for e in run_turn_stream(
            provider, _executor(tmp_path), system="", history=[], user_message="loop",
            max_iterations=2)
    ]
    assert isinstance(events[-1], TurnDone) and events[-1].stop_reason == "max_iterations"
    assert sum(isinstance(e, ToolResultEvent) for e in events) == 2


async def test_stream_rejects_zero_iterations(tmp_path):
    with pytest.raises(ValueError):
        async for _ in run_turn_stream(
            FakeProvider([]), _executor(tmp_path), system="", history=[],
            user_message="x", max_iterations=0):
            pass
```
> Reuses `_say`, `_call`, `_executor`, `Role`, `FakeProvider` already imported/defined in `test_loop.py` from Plan 2a.

- [ ] **Step 2: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_loop.py -v`
Expected: FAIL(`ImportError: cannot import name 'run_turn_stream'`)。

- [ ] **Step 3: 实现 run_turn_stream**

Edit `services/worker/src/agent_cloud_worker/loop.py` — add imports and the generator. Add to imports:
```python
from collections.abc import AsyncIterator

from agent_cloud_common import (
    CompletionRequest,
    Message,
    Role,
    TextDelta,
    ThinkingDelta,
    ToolCallStarted,
    ToolResultEvent,
    TurnDone,
    TurnEvent,
    Usage,
)

from agent_cloud_worker.provider import (
    ProviderCompleted,
    ProviderTextDelta,
    ProviderThinkingDelta,
    StreamingProvider,
)
```
(Keep existing imports; merge the common ones. `Provider` import stays for `run_turn`.)

Append the function:
```python
async def run_turn_stream(
    provider: StreamingProvider,
    executor: ToolExecutor,
    *,
    system: str,
    history: list[Message],
    user_message: str,
    max_iterations: int = 10,
) -> AsyncIterator[TurnEvent]:
    """流式版回合:消费 provider.stream 转发增量、执行工具并 yield 事件,最后 yield TurnDone。

    TurnDone 携带本回合新增的 assistant/tool 消息(供后端持久化);用户消息不计入。
    stop_reason="max_iterations" 表示回合未完成(可能止于 tool 消息),由调用方决定丢弃/重试。
    """
    if max_iterations < 1:
        raise ValueError("max_iterations must be >= 1")

    working: list[Message] = [*history, Message(role=Role.USER, text=user_message)]
    new_messages: list[Message] = []
    usage = Usage()

    for _ in range(max_iterations):
        completed: ProviderCompleted | None = None
        async for event in provider.stream(
            CompletionRequest(system=system, messages=list(working), tools=executor.specs())
        ):
            if isinstance(event, ProviderTextDelta):
                yield TextDelta(text=event.text)
            elif isinstance(event, ProviderThinkingDelta):
                yield ThinkingDelta(text=event.text)
            elif isinstance(event, ProviderCompleted):
                completed = event
        if completed is None:
            raise RuntimeError("provider stream ended without a ProviderCompleted event")

        usage.input_tokens += completed.usage.input_tokens
        usage.output_tokens += completed.usage.output_tokens
        assistant = completed.message
        working.append(assistant)
        new_messages.append(assistant)

        if not assistant.tool_calls:
            yield TurnDone(new_messages=new_messages, usage=usage, stop_reason="end_turn")
            return

        tool_results = []
        for call in assistant.tool_calls:
            yield ToolCallStarted(call_id=call.id, name=call.name, arguments=call.arguments)
            result = await executor.execute(call)
            yield ToolResultEvent(
                call_id=result.call_id, content=result.content, is_error=result.is_error
            )
            tool_results.append(result)
        tool_message = Message(role=Role.TOOL, tool_results=tool_results)
        working.append(tool_message)
        new_messages.append(tool_message)

    yield TurnDone(new_messages=new_messages, usage=usage, stop_reason="max_iterations")
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_loop.py -v`
Expected: PASS(原有 + 新 4)。

- [ ] **Step 5: 提交**

```bash
git add services/worker/src/agent_cloud_worker/loop.py services/worker/tests/test_loop.py
git commit -m "feat(worker): add run_turn_stream streaming turn loop"
```

---

### Task 3: 导出 + lint + README + 全回归

**Files:**
- Modify: `services/worker/src/agent_cloud_worker/__init__.py`, `services/worker/README.md`

- [ ] **Step 1: 导出**

Edit `services/worker/src/agent_cloud_worker/__init__.py`:
- 加 `from agent_cloud_worker.loop import run_turn_stream`(与现有 `run_turn, TurnResult` 同行合并)。
- 加 `from agent_cloud_worker.provider import ProviderCompleted, ProviderTextDelta, ProviderThinkingDelta, StreamingProvider`(与现有 provider 导入合并)。
- 在 `__all__` 加 `"run_turn_stream"`、`"StreamingProvider"`、`"ProviderTextDelta"`、`"ProviderThinkingDelta"`、`"ProviderCompleted"`。

- [ ] **Step 2: README 追加**

在 `services/worker/README.md` 末尾追加:
```markdown

## 流式(Plan 3a)
- `run_turn_stream(provider, executor, *, system, history, user_message)` — 异步生成器,yield 回合事件(`TextDelta`/`ToolCallStarted`/`ToolResultEvent`/`TurnDone` 等,定义于 `agent_cloud_common.events`)。
- `StreamingProvider.stream(request)` — 产生 provider 级事件(deltas + 最终 `ProviderCompleted`);`FakeProvider` 同时支持 `complete` 与 `stream`。
- 流式 gRPC(`RunTurnStream`)与后端 SSE 见 Plan 3b/3c。
```

- [ ] **Step 3: lint**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run ruff check --fix . && uv run ruff format .`
Expected: clean。(common 的 events.py 是手写的;如需 `cd packages/common && uv run ruff check src/agent_cloud_common`。)

- [ ] **Step 4: 全回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/packages/common && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest -q
```
Expected:common 4;worker 44(38 + provider 2 + loop 4);sandbox 23;backend 41。

- [ ] **Step 5: 提交**

```bash
git add services/worker/src/agent_cloud_worker/__init__.py services/worker/README.md
git commit -m "chore(worker): export streaming API and document it"
```

---

## Self-Review(写完后自检结果)

**Spec 覆盖(Plan 3a 范围)**:
- §7-② 流式事件(text_delta/thinking_delta/tool_call/tool_result/turn_done)→ common `events.py` + `run_turn_stream` yield 之。✓
- §8 回合循环(流式版):消费 provider 流 → 转发增量 → 执行工具 yield 事件 → 终止/上限 → `TurnDone`(含 new_messages 供持久化)。✓
- provider 抽象流式化:`StreamingProvider.stream` + `FakeProvider.stream`(同实例兼容 complete/stream)。✓
- 纯增量:`run_turn`/`Provider.complete` 不变;`run_turn_stream` 与事件类型是 3b 的接缝。✓
- 明确延后:流式 gRPC `RunTurnStream`(3b)、后端 SSE(3c)、事件↔proto 映射、流式工具 stdout、真实 provider。

**占位符扫描**:无 TBD;每步有完整代码或确切命令/预期。

**类型/命名一致性**:回合事件 `TextDelta/ThinkingDelta/ToolCallStarted/ToolResultEvent/TurnDone` 在 common 定义、worker loop yield、测试断言一致(与数据类型 `ToolCall`/`ToolResult` 区分命名);provider 事件 `ProviderTextDelta/ThinkingDelta/Completed` 在 provider 定义、loop 消费;`run_turn_stream(provider, executor, *, system, history, user_message, max_iterations=10)` 签名与测试一致;复用 2a 的 `ToolExecutor`/`LocalToolExecutor`/`CompletionRequest`/`Message`/`Role`/`Usage`;`ProviderCompleted` 结束契约由 loop 的 `completed is None` 守卫强制。
```
