# Plan 12a: Session Compaction — proto + common + worker

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** worker side of compaction — report accurate `context_tokens` (last LLM call's input_tokens), accept a `history_summary` (inject into system), a `Summarize` RPC (fold history → summary), and signal context-window-exceeded as `RESOURCE_EXHAUSTED`.

**Tech Stack:** protobuf (`scripts/gen_protos.sh`), grpc.aio, pytest. Spec: [2026-06-08-session-compaction-design.md](../specs/2026-06-08-session-compaction-design.md) §4–6.

Test exec: `cd services/worker && uv run pytest -q` (worker suite is in-process, no DB/RYUK).

---

## Task 1: proto changes + regenerate stubs

**Files:** `protos/agent_cloud/v1/worker.proto`, then `scripts/gen_protos.sh`.

- [ ] **Step 1: edit worker.proto** — add the Summarize RPC, `history_summary`, `context_tokens`:

```proto
service Worker {
  rpc RunTurn(RunTurnRequest) returns (RunTurnResponse);
  rpc RunTurnStream(RunTurnRequest) returns (stream TurnEvent);
  rpc Summarize(SummarizeRequest) returns (SummarizeResponse);
}
```
In `RunTurnRequest` add: `string history_summary = 11;`
In `RunTurnResponse` add: `int64 context_tokens = 5;`
In `TurnDone` add: `int64 context_tokens = 5;`
At the end add:
```proto
message SummarizeRequest {
  Agent agent = 1;
  string prior_summary = 2;
  repeated Msg messages = 3;
}
message SummarizeResponse {
  string summary = 1;
  int64 input_tokens = 2;
  int64 output_tokens = 3;
}
```

- [ ] **Step 2: regenerate**

Run: `bash scripts/gen_protos.sh`
Expected: `packages/common/src/agent_cloud/v1/worker_pb2.py` + `worker_pb2_grpc.py` regenerated (now have `Summarize`, `history_summary`, `context_tokens`, `SummarizeRequest/Response`). Verify: `cd services/worker && uv run python -c "from agent_cloud.v1 import worker_pb2; print(worker_pb2.RunTurnRequest().history_summary, worker_pb2.SummarizeRequest); print('context_tokens' in worker_pb2.TurnDone.DESCRIPTOR.fields_by_name)"`

- [ ] **Step 3: commit**
```bash
git add protos/agent_cloud/v1/worker.proto packages/common/src/agent_cloud/v1/
git commit -m "proto: Summarize RPC + RunTurnRequest.history_summary + context_tokens"
```

---

## Task 2: common TurnDone.context_tokens + codec

**Files:** `packages/common/src/agent_cloud_common/events.py`, `codec.py`; Test: `packages/common/tests/` (codec round-trip test if present, else worker covers it).

- [ ] **Step 1: add field to TurnDone dataclass** (`events.py:33`):
```python
@dataclass
class TurnDone:
    new_messages: list[Message]
    usage: Usage
    stop_reason: str
    context_tokens: int = 0
```

- [ ] **Step 2: codec** (`codec.py`) — carry `context_tokens` both ways:
- In `turn_event_to_proto` TurnDone branch (around line 77): add `context_tokens=event.context_tokens,` to `worker_pb2.TurnDone(...)`.
- In `turn_event_from_proto` TurnDone branch (around line 103): add `context_tokens=t.context_tokens,` to `TurnDone(...)`.

- [ ] **Step 3: verify**

Run: `cd services/worker && uv run python -c "
from agent_cloud_common import TurnDone, Usage
from agent_cloud_common.codec import turn_event_to_proto, turn_event_from_proto
d = TurnDone(new_messages=[], usage=Usage(input_tokens=3, output_tokens=4), stop_reason='end_turn', context_tokens=123)
r = turn_event_from_proto(turn_event_to_proto(d)); assert r.context_tokens == 123, r.context_tokens; print('ok', r.context_tokens)"`
Expected: `ok 123`.

- [ ] **Step 4: commit**
```bash
git add packages/common/src/agent_cloud_common/events.py packages/common/src/agent_cloud_common/codec.py
git commit -m "feat(common): TurnDone.context_tokens + codec round-trip"
```

---

## Task 3: worker loop reports context_tokens (last call's input_tokens)

**Files:** `services/worker/src/agent_cloud_worker/loop.py`; Test: `services/worker/tests/test_loop.py` (or wherever run_turn is tested).

- [ ] **Step 1: failing test** — assert context_tokens == the LAST completion's input_tokens, not the sum. In the worker tests (FakeProvider lets you script per-call usage), add:
```python
async def test_context_tokens_is_last_call_input_not_sum():
    # 两次 LLM 调用(第一次有工具调用),input_tokens 分别 100、250 → context_tokens 应=250(最后一次),usage.input_tokens=350(累加)
    from agent_cloud_common import CompletionResult, Message, Role, ToolCall, Usage
    from agent_cloud_worker.loop import run_turn
    from agent_cloud_worker.provider import FakeProvider
    from agent_cloud_worker.tools import LocalToolExecutor  # 或现有的假 executor
    provider = FakeProvider([
        CompletionResult(message=Message(role=Role.ASSISTANT, tool_calls=[ToolCall(id="c1", name="bash", arguments={"command": "echo hi"})]), usage=Usage(input_tokens=100, output_tokens=10)),
        CompletionResult(message=Message(role=Role.ASSISTANT, text="done"), usage=Usage(input_tokens=250, output_tokens=20)),
    ])
    # executor: 任意能执行 bash 的;断言 context_tokens
    ...
    assert result.usage.input_tokens == 350
    assert result.context_tokens == 250
```
(Adapt to the existing test fixtures for a tool-executing run; the key asserts are the two lines.)

- [ ] **Step 2: implement** — in `loop.py`:
- `TurnResult` add `context_tokens: int = 0`.
- `run_turn`: before the loop `last_input = 0`; inside, after `usage.input_tokens += result.usage.input_tokens` add `last_input = result.usage.input_tokens`; both `return TurnResult(...)` add `context_tokens=last_input`.
- `run_turn_stream`: same — `last_input = 0`; after `usage.input_tokens += completed.usage.input_tokens` add `last_input = completed.usage.input_tokens`; both `yield TurnDone(...)` add `context_tokens=last_input`.

- [ ] **Step 3: run worker suite → pass; commit**
```bash
cd services/worker && uv run pytest -q
git add services/worker/src/agent_cloud_worker/loop.py services/worker/tests/
git commit -m "feat(worker): report context_tokens (last LLM call input_tokens) on turn result"
```

---

## Task 4: worker injects history_summary into system

**Files:** `services/worker/src/agent_cloud_worker/context.py` (or wherever `_build_context_and_history` lives — check `server.py` import); Test: `services/worker/tests/test_context.py`.

- [ ] **Step 1: failing test** (`test_context.py`):
```python
def test_history_summary_injected_into_system():
    # build_system_prompt 或 _build_context_and_history 应把摘要拼进 system
    from agent_cloud_worker.context import build_system_prompt
    out = build_system_prompt(documents=[], memory=[], skills=[], history_summary="早期:用户要做排序,已完成 bubble。")
    assert "早期:用户要做排序" in out
    assert "摘要" in out  # 有个小标题
```
(If the summary is injected in `server.py`'s `_build_context_and_history` rather than `build_system_prompt`, test there instead. Prefer adding a `history_summary: str = ""` param to `build_system_prompt`.)

- [ ] **Step 2: implement** — `build_system_prompt(..., history_summary: str = "")`: if `history_summary`, append a section `f"# 此前对话摘要\n{history_summary}"` (after BASE_SYSTEM_PROMPT, before/with docs). And in `server.py` `_build_context_and_history`, pass `request.history_summary` through.

- [ ] **Step 3: run → pass; commit**
```bash
cd services/worker && uv run pytest tests/test_context.py -q
git add services/worker/src/agent_cloud_worker/context.py services/worker/src/agent_cloud_worker/server.py services/worker/tests/test_context.py
git commit -m "feat(worker): inject history_summary into the system prompt"
```

---

## Task 5: Summarize handler + context-exceeded → RESOURCE_EXHAUSTED

**Files:** `services/worker/src/agent_cloud_worker/server.py`, `openai_provider.py`; Test: `services/worker/tests/test_server.py` / `test_summarize.py`.

- [ ] **Step 1: failing test** — `Summarize` returns a summary from one completion (FakeProvider):
```python
async def test_summarize_returns_summary(...):
    # 用假 provider_factory 返回 FakeProvider([_final("摘要:做了X")]);调 WorkerServicer.Summarize
    from agent_cloud.v1 import worker_pb2
    req = worker_pb2.SummarizeRequest(
        agent=worker_pb2.Agent(model="m", provider="p"),
        prior_summary="",
        messages=[worker_pb2.Msg(role="user", text="帮我排序"), worker_pb2.Msg(role="assistant", text="好的")],
    )
    resp = await servicer.Summarize(req, _ctx())
    assert "摘要" in resp.summary
```
(Mirror the existing `test_server.py` setup: a WorkerServicer with an injected `provider_factory`, and a fake gRPC context.)

- [ ] **Step 2: implement Summarize** (`server.py` `WorkerServicer`):
```python
_SUMMARIZE_SYSTEM = (
    "你是对话压缩器。把给定对话浓缩成简明要点,保留:用户目标、关键事实与决定、"
    "产出的文件、未完成事项。保留后续对话需要的信息,去掉寒暄与冗余。只输出要点本身。"
)

async def Summarize(self, request, context):
    from agent_cloud_common import CompletionRequest, Message, Role
    from agent_cloud_common.codec import msg_from_proto
    try:
        provider = self._provider_factory(request.agent.model, request.agent.provider, request.agent.key_ref)
    except Exception as exc:
        await context.abort(grpc.StatusCode.FAILED_PRECONDITION, f"provider unavailable: {exc}")
    history = [msg_from_proto(m) for m in request.messages]
    instruction = "请将以上对话压缩成简明要点。"
    if request.prior_summary:
        instruction += f"\n已有摘要(合并更新):\n{request.prior_summary}"
    messages = [*history, Message(role=Role.USER, text=instruction)]
    try:
        result = await provider.complete(CompletionRequest(system=_SUMMARIZE_SYSTEM, messages=messages, tools=[]))
    except grpc.aio.AioRpcError:
        raise
    except Exception as exc:
        await context.abort(grpc.StatusCode.INTERNAL, f"summarize failed: {exc}")
    return worker_pb2.SummarizeResponse(
        summary=result.message.text,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
    )
```

- [ ] **Step 3: context-window-exceeded detection** (`openai_provider.py`):
- Add an exception type (e.g. in provider.py or openai_provider.py): `class ContextWindowExceeded(Exception): ...`
- In `complete` and `stream`, wrap the OpenAI call; on `openai.BadRequestError` (400) whose message/code indicates context length (`code == "context_length_exceeded"` or message lower-cased contains any of `"context length"`, `"maximum context"`, `"too long"`, `"reduce the length"`, `"context window"`), raise `ContextWindowExceeded(...)`.

- [ ] **Step 4: map it in RunTurn/RunTurnStream** (`server.py`): wrap the `run_turn`/`run_turn_stream` execution; on `ContextWindowExceeded` → `await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "context window exceeded")` (distinct from the INTERNAL used for other provider failures).

- [ ] **Step 5: test the mapping** — a FakeProvider that raises `ContextWindowExceeded` → RunTurn aborts RESOURCE_EXHAUSTED:
```python
async def test_context_exceeded_maps_to_resource_exhausted(...):
    # provider.complete raises ContextWindowExceeded → servicer.RunTurn → context.abort(RESOURCE_EXHAUSTED)
    ...
    assert ctx.abort_code == grpc.StatusCode.RESOURCE_EXHAUSTED
```

- [ ] **Step 6: full worker suite + ruff + commit**
```bash
cd services/worker && uv run pytest -q && uv run ruff check src/ tests/
git add services/worker/src/agent_cloud_worker/ services/worker/tests/
git commit -m "feat(worker): Summarize RPC + context-window-exceeded -> RESOURCE_EXHAUSTED"
```

---

## Self-Review
- Spec coverage §4 (proto) ✓ §5 (common context_tokens; Summarize uses proto directly from backend — no common type needed) ✓ §6 (loop context_tokens, history_summary in system, Summarize handler, context-exceeded→RESOURCE_EXHAUSTED) ✓.
- context_tokens = last call's input (not sum) — explicit test.
- No placeholders for substantive logic; test fixtures said to mirror existing `test_server.py`/`test_loop.py` patterns (verify exact FakeProvider/ctx helpers at execution).
