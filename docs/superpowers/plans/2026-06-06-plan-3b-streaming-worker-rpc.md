# Plan 3b: 流式 worker RPC(RunTurnStream) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `run_turn_stream` 暴露为 gRPC server-streaming:`worker.proto` 加 `RunTurnStream`(返回 `stream TurnEvent`)+ 事件↔proto 转换(common codec)+ worker 流式服务器。端到端:消费 worker 的事件流 over gRPC + 真沙箱执行工具。

**Architecture:** `worker.proto` 复用现有 `RunTurnRequest`,新增 `TurnEvent`(oneof:text_delta/thinking_delta/tool_call_started/tool_result/turn_done)与 `rpc RunTurnStream(RunTurnRequest) returns (stream TurnEvent)`。common `codec` 加 `turn_event_to_proto`/`turn_event_from_proto`。worker `server.py` 把 `RunTurn` 的解码逻辑抽成 `_build_context_and_history` 复用,新增 `RunTurnStream`(server-streaming async generator):解码(失败 `context.abort`)→ 拨号沙箱 → `async for event in run_turn_stream(...): yield turn_event_to_proto(event)`。

**Tech Stack:** Python 3.12+、grpcio(grpc.aio server-streaming)、pytest + pytest-asyncio + ruff。仍 FakeProvider;**无 DB/Docker**(e2e 起内嵌 worker + sandbox)。

参考:spec §6/§7-②;已合并:3a(`run_turn_stream` + common 事件)、2c(`worker.proto` `RunTurn`、worker server、common `codec`)、2b(沙箱、`SandboxToolExecutor`)。

## 范围

**做**:`RunTurnStream` proto + 事件↔proto codec + worker 流式服务器 + e2e。

**不做(Plan 3c)**:后端 SSE 代理、`turn_done` 落库。流式 stdout(工具级)与真实 provider 仍后续。

## File Structure

```
protos/agent_cloud/v1/worker.proto             # +TurnEvent oneof 消息, +RunTurnStream rpc
packages/common/src/agent_cloud/v1/worker_pb2*.py  # 重新生成(提交)
packages/common/src/agent_cloud_common/codec.py    # +turn_event_to_proto / turn_event_from_proto
packages/common/tests/test_codec.py                # +事件 round-trip 测试
services/worker/src/agent_cloud_worker/server.py    # 抽 _build_context_and_history;+RunTurnStream
services/worker/tests/test_worker_server.py         # +流式 e2e + decode-error abort 测试
```

---

### Task 0: worker.proto 加 TurnEvent + RunTurnStream + 代码生成

**Files:**
- Modify: `protos/agent_cloud/v1/worker.proto`
- Generated (commit): `packages/common/src/agent_cloud/v1/worker_pb2.py`, `worker_pb2_grpc.py`

- [ ] **Step 1: 编辑 worker.proto**

In `protos/agent_cloud/v1/worker.proto`, add to the `Worker` service a second rpc (keep `RunTurn`):
```proto
service Worker {
  rpc RunTurn(RunTurnRequest) returns (RunTurnResponse);
  rpc RunTurnStream(RunTurnRequest) returns (stream TurnEvent);
}
```
And append these message definitions at the end of the file:
```proto
message TextDelta { string text = 1; }
message ThinkingDelta { string text = 1; }
message ToolCallStarted {
  string call_id = 1;
  string name = 2;
  string arguments_json = 3;
}
message ToolResultEvent {
  string call_id = 1;
  string content = 2;
  bool is_error = 3;
}
message TurnDone {
  repeated Msg new_messages = 1;
  int64 input_tokens = 2;
  int64 output_tokens = 3;
  string stop_reason = 4;
}
message TurnEvent {
  oneof event {
    TextDelta text_delta = 1;
    ThinkingDelta thinking_delta = 2;
    ToolCallStarted tool_call_started = 3;
    ToolResultEvent tool_result = 4;
    TurnDone turn_done = 5;
  }
}
```

- [ ] **Step 2: 生成**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud && bash scripts/gen_protos.sh`
Expected: `worker_pb2.py`/`worker_pb2_grpc.py` 重新生成,含 `TurnEvent`、`RunTurnStream`。

- [ ] **Step 3: 验证导入**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run python -c "from agent_cloud.v1 import worker_pb2; e=worker_pb2.TurnEvent(text_delta=worker_pb2.TextDelta(text='x')); print(e.WhichOneof('event'), e.text_delta.text)"`
Expected: 打印 `text_delta x`。若桩内是裸相对导入失败,STOP 报 BLOCKED(同前)。

- [ ] **Step 4: 提交**

```bash
git add protos/agent_cloud/v1/worker.proto packages/common/src/agent_cloud/v1/worker_pb2.py packages/common/src/agent_cloud/v1/worker_pb2_grpc.py
git commit -m "chore(grpc): add RunTurnStream and TurnEvent to worker proto"
```

---

### Task 1: 事件↔proto codec(common)

**Files:**
- Modify: `packages/common/src/agent_cloud_common/codec.py`
- Test: `packages/common/tests/test_codec.py`

- [ ] **Step 1: 写失败测试(追加)**

Append to `packages/common/tests/test_codec.py`:
```python
from agent_cloud_common import (
    TextDelta, ThinkingDelta, ToolCallStarted, ToolResultEvent, TurnDone, Usage,
)
from agent_cloud_common.codec import turn_event_from_proto, turn_event_to_proto


def test_round_trip_text_delta():
    e = turn_event_from_proto(turn_event_to_proto(TextDelta(text="hi")))
    assert isinstance(e, TextDelta) and e.text == "hi"


def test_round_trip_thinking_delta():
    e = turn_event_from_proto(turn_event_to_proto(ThinkingDelta(text="hmm")))
    assert isinstance(e, ThinkingDelta) and e.text == "hmm"


def test_round_trip_tool_call_started():
    e = turn_event_from_proto(turn_event_to_proto(
        ToolCallStarted(call_id="c1", name="bash", arguments={"command": "echo x"})))
    assert isinstance(e, ToolCallStarted)
    assert e.call_id == "c1" and e.name == "bash" and e.arguments == {"command": "echo x"}


def test_round_trip_tool_result_event():
    e = turn_event_from_proto(turn_event_to_proto(
        ToolResultEvent(call_id="c1", content="out", is_error=True)))
    assert isinstance(e, ToolResultEvent) and e.is_error is True and e.content == "out"


def test_round_trip_turn_done():
    e = turn_event_from_proto(turn_event_to_proto(
        TurnDone(new_messages=[Message(role=Role.ASSISTANT, text="done")],
                 usage=Usage(input_tokens=3, output_tokens=4), stop_reason="end_turn")))
    assert isinstance(e, TurnDone)
    assert e.new_messages[0].text == "done" and e.new_messages[0].role == Role.ASSISTANT
    assert e.usage.output_tokens == 4 and e.stop_reason == "end_turn"
```
> `Message`/`Role` already imported at the top of `test_codec.py` (Plan 2c).

- [ ] **Step 2: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/packages/common && uv run pytest tests/test_codec.py -v`
Expected: FAIL(`ImportError: cannot import name 'turn_event_to_proto'`)。

- [ ] **Step 3: 实现 codec(追加到 codec.py)**

Append to `packages/common/src/agent_cloud_common/codec.py`:
```python
from agent_cloud_common.events import (
    TextDelta,
    ThinkingDelta,
    ToolCallStarted,
    ToolResultEvent,
    TurnDone,
    TurnEvent,
)
from agent_cloud_common.types import Usage


def turn_event_to_proto(event: TurnEvent) -> worker_pb2.TurnEvent:
    if isinstance(event, TextDelta):
        return worker_pb2.TurnEvent(text_delta=worker_pb2.TextDelta(text=event.text))
    if isinstance(event, ThinkingDelta):
        return worker_pb2.TurnEvent(thinking_delta=worker_pb2.ThinkingDelta(text=event.text))
    if isinstance(event, ToolCallStarted):
        return worker_pb2.TurnEvent(
            tool_call_started=worker_pb2.ToolCallStarted(
                call_id=event.call_id, name=event.name,
                arguments_json=json.dumps(event.arguments),
            )
        )
    if isinstance(event, ToolResultEvent):
        return worker_pb2.TurnEvent(
            tool_result=worker_pb2.ToolResultEvent(
                call_id=event.call_id, content=event.content, is_error=event.is_error
            )
        )
    if isinstance(event, TurnDone):
        return worker_pb2.TurnEvent(
            turn_done=worker_pb2.TurnDone(
                new_messages=[msg_to_proto(m) for m in event.new_messages],
                input_tokens=event.usage.input_tokens,
                output_tokens=event.usage.output_tokens,
                stop_reason=event.stop_reason,
            )
        )
    raise ValueError(f"unknown turn event type: {type(event).__name__}")


def turn_event_from_proto(proto: worker_pb2.TurnEvent) -> TurnEvent:
    which = proto.WhichOneof("event")
    if which == "text_delta":
        return TextDelta(text=proto.text_delta.text)
    if which == "thinking_delta":
        return ThinkingDelta(text=proto.thinking_delta.text)
    if which == "tool_call_started":
        t = proto.tool_call_started
        return ToolCallStarted(
            call_id=t.call_id, name=t.name, arguments=json.loads(t.arguments_json or "{}")
        )
    if which == "tool_result":
        t = proto.tool_result
        return ToolResultEvent(call_id=t.call_id, content=t.content, is_error=t.is_error)
    if which == "turn_done":
        t = proto.turn_done
        return TurnDone(
            new_messages=[msg_from_proto(m) for m in t.new_messages],
            usage=Usage(input_tokens=t.input_tokens, output_tokens=t.output_tokens),
            stop_reason=t.stop_reason,
        )
    raise ValueError(f"empty or unknown TurnEvent oneof: {which!r}")
```
> Note: `json`, `msg_to_proto`, `msg_from_proto`, `worker_pb2` are already imported at the top of `codec.py` (Plan 2c). Add only the new `events`/`Usage` imports shown.

- [ ] **Step 4: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/packages/common && uv run pytest tests/test_codec.py -v`
Expected: PASS(原 4 + 新 5 = 9)。

- [ ] **Step 5: 提交**

```bash
git add packages/common/src/agent_cloud_common/codec.py packages/common/tests/test_codec.py
git commit -m "feat(common): add TurnEvent<->proto codec"
```

---

### Task 2: worker 流式服务器(RunTurnStream)+ e2e

**Files:**
- Modify: `services/worker/src/agent_cloud_worker/server.py`
- Test: `services/worker/tests/test_worker_server.py`

- [ ] **Step 1: 写失败测试(追加到 test_worker_server.py)**

Append to `services/worker/tests/test_worker_server.py`:
```python
import grpc
import pytest

from agent_cloud_common import TextDelta, ToolCallStarted, ToolResultEvent, TurnDone
from agent_cloud_common.codec import turn_event_from_proto


async def test_run_turn_stream_over_grpc(sandbox):
    sandbox_addr, base = sandbox
    provider = FakeProvider([
        _call("write_file", {"path": "hello.txt", "content": "from-agent"}),
        _final("done"),
    ])
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider, port=0)
    events = []
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            async for proto_ev in stub.RunTurnStream(worker_pb2.RunTurnRequest(
                agent=worker_pb2.Agent(model="m", provider="fake"),
                messages=[], user_message="write it",
                sandbox_endpoint=sandbox_addr, work_subdir="s1",
            )):
                events.append(turn_event_from_proto(proto_ev))
    finally:
        await worker_server.stop(None)

    kinds = [type(e).__name__ for e in events]
    assert "ToolCallStarted" in kinds and "ToolResultEvent" in kinds
    assert isinstance(events[-1], TurnDone) and events[-1].stop_reason == "end_turn"
    assert [m.role.value for m in events[-1].new_messages] == ["assistant", "tool", "assistant"]
    assert (base / "s1" / "hello.txt").read_text() == "from-agent"


async def test_run_turn_stream_invalid_role_aborts(sandbox):
    sandbox_addr, _ = sandbox
    provider = FakeProvider([_final("x")])
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            with pytest.raises(grpc.aio.AioRpcError) as ei:
                async for _ in stub.RunTurnStream(worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    messages=[worker_pb2.Msg(role="system", text="bad")],
                    user_message="x", sandbox_endpoint=sandbox_addr, work_subdir="s1",
                )):
                    pass
    finally:
        await worker_server.stop(None)
    assert ei.value.code() == grpc.StatusCode.INVALID_ARGUMENT
```
> `sandbox` fixture, `FakeProvider`, `_call`, `_final`, `create_worker_server`, `worker_pb2`, `worker_pb2_grpc` already present in `test_worker_server.py` (Plan 2c).

- [ ] **Step 2: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_worker_server.py -v`
Expected: FAIL(`grpc ... UNIMPLEMENTED` 或方法不存在)。

- [ ] **Step 3: 实现 RunTurnStream(重构 server.py)**

Edit `services/worker/src/agent_cloud_worker/server.py`. Add imports:
```python
from agent_cloud_common.codec import msg_from_proto, msg_to_proto, turn_event_to_proto
from agent_cloud_worker.loop import run_turn, run_turn_stream
```
(merge with existing imports; `run_turn` already imported).

Extract the shared decode into a module-level helper (place above the class):
```python
def _build_context_and_history(request: worker_pb2.RunTurnRequest) -> tuple[str, list]:
    system = build_system_prompt(
        documents=[ContextDocument(d.scope, d.type, d.content) for d in request.documents],
        memory=[MemoryItem(m.scope, m.content) for m in request.memory],
        skills=[SkillRef(s.name, s.description, s.location) for s in request.skills],
    )
    history = [msg_from_proto(m) for m in request.messages]
    return system, history
```

Refactor `RunTurn` to use it (replace the inline system/history build in `RunTurn` with):
```python
        try:
            system, history = _build_context_and_history(request)
        except (ValueError, json.JSONDecodeError) as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        try:
            provider = self._provider_factory(
                request.agent.model, request.agent.provider, request.agent.key_ref
            )
        except Exception as exc:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, f"provider unavailable: {exc}")
```
(Keep the rest of `RunTurn` — the sandbox channel + `run_turn` + `RunTurnResponse` — unchanged.)

Add the streaming method to the `WorkerServicer` class:
```python
    async def RunTurnStream(self, request, context):
        try:
            system, history = _build_context_and_history(request)
        except (ValueError, json.JSONDecodeError) as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        try:
            provider = self._provider_factory(
                request.agent.model, request.agent.provider, request.agent.key_ref
            )
        except Exception as exc:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, f"provider unavailable: {exc}")

        options = [
            ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
            ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
        ]
        async with grpc.aio.insecure_channel(request.sandbox_endpoint, options=options) as channel:
            executor = SandboxToolExecutor(channel, request.work_subdir)
            async for event in run_turn_stream(
                provider, executor,
                system=system, history=history, user_message=request.user_message,
            ):
                yield turn_event_to_proto(event)
```
> `MAX_GRPC_MESSAGE_BYTES`, `ContextDocument`, `MemoryItem`, `SkillRef`, `build_system_prompt`, `SandboxToolExecutor`, `json`, `grpc` are already imported in `server.py` (Plan 2c). Ensure `json` is imported (add `import json` if missing).

- [ ] **Step 4: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_worker_server.py -v`
Expected: PASS(原 2c 的 RunTurn 测试仍过 + 新 2)。

- [ ] **Step 5: 提交**

```bash
git add services/worker/src/agent_cloud_worker/server.py services/worker/tests/test_worker_server.py
git commit -m "feat(worker): add RunTurnStream server-streaming gRPC with e2e"
```

---

### Task 3: lint + README + 全回归

**Files:**
- Modify: `services/worker/README.md`

- [ ] **Step 1: lint**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run ruff check --fix . && uv run ruff format .` ; `cd /Users/wuhaowen/src/llm-agent/agent-cloud/packages/common && uv run ruff check src/agent_cloud_common`
Expected: clean(生成桩不 lint)。

- [ ] **Step 2: README 追加**

在 `services/worker/README.md` 的"流式(Plan 3a)"节后追加:
```markdown
- gRPC:`RunTurnStream(RunTurnRequest) returns (stream TurnEvent)`(`worker.proto`)。事件↔proto 由 `agent_cloud_common.codec.turn_event_to_proto/from_proto` 转换。后端 SSE 代理见 Plan 3c。
```

- [ ] **Step 3: 全回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/packages/common && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest -q
```
Expected:common 9(4 + 5 事件 round-trip);worker 46(44 + 2 流式 server);sandbox 23;backend 41。

- [ ] **Step 4: 提交**

```bash
git add services/worker/README.md
git commit -m "docs(worker): document RunTurnStream"
```

---

## Self-Review(写完后自检结果)

**Spec 覆盖(Plan 3b 范围)**:
- §6/§7-② 流式 gRPC:`RunTurnStream` server-streaming + `TurnEvent` oneof(text_delta/thinking_delta/tool_call_started/tool_result/turn_done)。✓
- 事件↔proto 映射(后端 3c 复用)→ common `codec.turn_event_to_proto/from_proto`。✓
- worker 流式服务器跑 `run_turn_stream`、拨号沙箱、yield proto 事件;解码错误 `context.abort(INVALID_ARGUMENT/FAILED_PRECONDITION)`(与 `RunTurn` 一致,经抽取的 `_build_context_and_history` DRY)。✓
- e2e:over gRPC 消费事件流 + 真沙箱执行 + decode-error abort。✓
- 明确延后:后端 SSE/落库(3c)、流式工具 stdout、真实 provider。

**占位符扫描**:无 TBD;生成桩由脚本产出并提交;其余每步完整代码或确切命令/预期。

**类型/命名一致性**:proto `TurnEvent` oneof 字段(text_delta/thinking_delta/tool_call_started/tool_result/turn_done)与 codec 的 `WhichOneof` 分派一致;proto 消息名(`TextDelta`/`ThinkingDelta`/`ToolCallStarted`/`ToolResultEvent`/`TurnDone`)经 `worker_pb2.` 前缀,与 common 同名 dataclass 不冲突;复用 3a 的 `run_turn_stream` 与 common 事件、2c 的 `msg_to_proto/from_proto`/`RunTurnRequest`/`Msg`/`MAX_GRPC_MESSAGE_BYTES`/`create_server(provider_factory,...)`、2b 的 `SandboxToolExecutor`;`RunTurnStream` 复用 `RunTurnRequest`(与 `RunTurn` 同请求,仅响应改为 stream)。
```
