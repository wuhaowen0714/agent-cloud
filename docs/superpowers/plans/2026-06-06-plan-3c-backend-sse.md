# Plan 3c: 后端 SSE(流式回合收官) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 后端把 worker 的 `RunTurnStream` gRPC 事件流代理成 **SSE** 推给前端:`POST /sessions/{id}/turn/stream` → 加会话锁 → 持久化 user 消息 → 组装请求 → 消费 worker 事件流 → 逐事件转 SSE → `turn_done` 时落库新消息并随事件回传 message_ids → 释放锁。流式链路收官。

**Architecture:** 新增 `turn/worker_client.stream_turn_via_worker`(异步生成器,持 channel 消费 `RunTurnStream`)。`turn/sse.py` 把 common 回合事件映射成前端 SSE JSON(spec §7-② 命名)。`api/turn.py` 加流式端点:前置步骤(锁/落 user/组装)用请求级 DI session 并提交;返回 `StreamingResponse`,其异步生成器用**全新 session**(`get_sessionmaker`)做 `turn_done` 落库与锁释放(避免 DI session 在长流期间的生命周期坑)。错误以 in-band SSE `error` 事件下发,不泄露内部异常。

**Tech Stack:** Python 3.12+、FastAPI `StreamingResponse`(text/event-stream)、grpcio aio client-streaming-consume、pytest + testcontainers + pytest-asyncio。e2e 起真 sandbox + 真 worker(FakeProvider)+ 后端。

参考:spec §6(SSE)、§7-②(事件)、§8、§10;已合并:3b(`RunTurnStream` + 事件 codec)、2d(锁 / `build_run_turn_request` / `common_to_content` / 一元 turn 端点)。

## 范围

**做**:worker 流式客户端、SSE 事件映射、流式端点 + 代理生成器(落库 + 释放锁 + 错误事件)、单元 + 全链路 e2e。

**不做**:每用户 sandbox 路由(Plan 4)、skills(Plan 5)、真实 provider。一元 `POST /sessions/{id}/turn`(2d)保留。

## SSE 事件契约(前端,spec §7-②)
- `{"type":"text_delta","text":...}`、`{"type":"thinking_delta","text":...}`
- `{"type":"tool_call_start","call_id":...,"tool":...,"args":{...}}`
- `{"type":"tool_result","call_id":...,"result":...,"is_error":...}`
- `{"type":"turn_done","usage":{"input_tokens":..,"output_tokens":..},"message_ids":[...],"stop_reason":...}`
- `{"type":"error","message":<generic>,"recoverable":bool}`
每条以 `data: <json>\n\n` 下发。

## File Structure

```
services/backend/src/agent_cloud_backend/turn/worker_client.py   # +stream_turn_via_worker
services/backend/src/agent_cloud_backend/turn/sse.py             # turn_event_to_sse, format_sse, error mapping
services/backend/src/agent_cloud_backend/api/turn.py             # +POST .../turn/stream + _sse_stream 生成器
services/backend/tests/test_sse.py                               # 映射单测
services/backend/tests/test_turn_stream_endpoint.py              # 端点单测(假 worker 流)
services/backend/tests/test_turn_stream_e2e.py                   # 全链路 SSE e2e
```

---

### Task 0: worker 流式客户端

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/turn/worker_client.py`

- [ ] **Step 1: 追加 stream_turn_via_worker**

Append to `services/backend/src/agent_cloud_backend/turn/worker_client.py`:
```python
from collections.abc import AsyncIterator


async def stream_turn_via_worker(
    worker_endpoint: str, request: worker_pb2.RunTurnRequest
) -> AsyncIterator[worker_pb2.TurnEvent]:
    """消费 worker 的 RunTurnStream;channel 在迭代期间保持打开。"""
    options = [
        ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
        ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
    ]
    async with grpc.aio.insecure_channel(worker_endpoint, options=options) as channel:
        stub = worker_pb2_grpc.WorkerStub(channel)
        async for event in stub.RunTurnStream(request):
            yield event
```
> `grpc`, `worker_pb2`, `worker_pb2_grpc`, `MAX_GRPC_MESSAGE_BYTES` are already imported at the top of `worker_client.py` (Plan 2d). Add only `from collections.abc import AsyncIterator` (at top, with the other imports).

- [ ] **Step 2: 冒烟导入**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run python -c "from agent_cloud_backend.turn.worker_client import stream_turn_via_worker; print('ok')"`
Expected: `ok`。

- [ ] **Step 3: 提交**

```bash
git add services/backend/src/agent_cloud_backend/turn/worker_client.py
git commit -m "feat(backend): add worker RunTurnStream client"
```

---

### Task 1: SSE 事件映射

**Files:**
- Create: `services/backend/src/agent_cloud_backend/turn/sse.py`
- Test: `services/backend/tests/test_sse.py`

- [ ] **Step 1: 写失败测试**

Create `services/backend/tests/test_sse.py`:
```python
import grpc
import pytest

from agent_cloud_backend.turn.sse import error_sse, format_sse, turn_event_to_sse
from agent_cloud_common import TextDelta, ThinkingDelta, ToolCallStarted, ToolResultEvent


def test_text_delta_mapping():
    assert turn_event_to_sse(TextDelta(text="hi")) == {"type": "text_delta", "text": "hi"}


def test_thinking_delta_mapping():
    assert turn_event_to_sse(ThinkingDelta(text="hmm")) == {"type": "thinking_delta", "text": "hmm"}


def test_tool_call_start_mapping():
    out = turn_event_to_sse(ToolCallStarted(call_id="c1", name="bash", arguments={"command": "x"}))
    assert out == {"type": "tool_call_start", "call_id": "c1", "tool": "bash", "args": {"command": "x"}}


def test_tool_result_mapping():
    out = turn_event_to_sse(ToolResultEvent(call_id="c1", content="out", is_error=True))
    assert out == {"type": "tool_result", "call_id": "c1", "result": "out", "is_error": True}


def test_format_sse():
    assert format_sse({"type": "text_delta", "text": "hi"}) == 'data: {"type": "text_delta", "text": "hi"}\n\n'


def test_error_sse_recoverable_codes():
    e = error_sse(grpc.StatusCode.UNAVAILABLE)
    assert e["type"] == "error" and e["recoverable"] is True
    assert "UNAVAILABLE" not in e["message"]  # generic, no internal detail
    e2 = error_sse(grpc.StatusCode.INVALID_ARGUMENT)
    assert e2["recoverable"] is False
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_sse.py -v`
Expected: FAIL(`ModuleNotFoundError: agent_cloud_backend.turn.sse`)。

- [ ] **Step 3: 实现 sse.py**

Create `services/backend/src/agent_cloud_backend/turn/sse.py`:
```python
from __future__ import annotations

import json

import grpc

from agent_cloud_common import TextDelta, ThinkingDelta, ToolCallStarted, ToolResultEvent

_RECOVERABLE = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.INTERNAL,
    grpc.StatusCode.DEADLINE_EXCEEDED,
}


def turn_event_to_sse(event) -> dict:
    """把流式回合事件(非 TurnDone)映射成前端 SSE JSON。TurnDone 由端点单独处理。"""
    if isinstance(event, TextDelta):
        return {"type": "text_delta", "text": event.text}
    if isinstance(event, ThinkingDelta):
        return {"type": "thinking_delta", "text": event.text}
    if isinstance(event, ToolCallStarted):
        return {"type": "tool_call_start", "call_id": event.call_id,
                "tool": event.name, "args": event.arguments}
    if isinstance(event, ToolResultEvent):
        return {"type": "tool_result", "call_id": event.call_id,
                "result": event.content, "is_error": event.is_error}
    raise ValueError(f"unmapped streaming event: {type(event).__name__}")


def error_sse(code: grpc.StatusCode) -> dict:
    recoverable = code in _RECOVERABLE
    message = "the turn was interrupted, please retry" if recoverable else "the request was rejected"
    return {"type": "error", "message": message, "recoverable": recoverable}


def format_sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_sse.py -v`
Expected: PASS(6 passed)。

- [ ] **Step 5: 提交**

```bash
git add services/backend/src/agent_cloud_backend/turn/sse.py services/backend/tests/test_sse.py
git commit -m "feat(backend): add SSE event mapping for turn events"
```

---

### Task 2: 流式端点 + 代理生成器

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/api/turn.py`
- Test: `services/backend/tests/test_turn_stream_endpoint.py`

- [ ] **Step 1: 写失败测试(假 worker 流)**

Create `services/backend/tests/test_turn_stream_endpoint.py`:
```python
import json

from agent_cloud_common import (
    Message, Role, TextDelta, ToolCallStarted, ToolResultEvent, TurnDone, Usage,
)
from agent_cloud_common.codec import turn_event_to_proto


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.strip().split("\n\n"):
        line = block.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:"):].strip()))
    return events


async def _make_session(client):
    uid = (await client.post("/users", json={"email": "s@example.com"})).json()["id"]
    aid = (await client.post("/agent-configs",
           json={"user_id": uid, "name": "c", "model": "m", "provider": "p"})).json()["id"]
    return (await client.post("/sessions", json={"user_id": uid, "agent_config_id": aid})).json()["id"]


def _fake_stream(monkeypatch):
    async def _gen(worker_endpoint, request):
        events = [
            TextDelta(text="hel"),
            TextDelta(text="lo"),
            ToolCallStarted(call_id="c1", name="bash", arguments={"command": "echo hi"}),
            ToolResultEvent(call_id="c1", content="hi\n", is_error=False),
            TurnDone(
                new_messages=[
                    Message(role=Role.ASSISTANT, text="hello"),
                    Message(role=Role.TOOL),
                    Message(role=Role.ASSISTANT, text="done"),
                ],
                usage=Usage(input_tokens=5, output_tokens=7), stop_reason="end_turn"),
        ]
        for e in events:
            yield turn_event_to_proto(e)

    from agent_cloud_backend.api import turn as turn_module
    monkeypatch.setattr(turn_module, "stream_turn_via_worker", _gen)


async def test_stream_endpoint_emits_events_and_persists(client, monkeypatch):
    _fake_stream(monkeypatch)
    sid = await _make_session(client)
    resp = await client.post(f"/sessions/{sid}/turn/stream", json={"content": "say hi"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    kinds = [e["type"] for e in events]
    assert kinds == ["text_delta", "text_delta", "tool_call_start", "tool_result", "turn_done"]
    done = events[-1]
    assert done["stop_reason"] == "end_turn" and len(done["message_ids"]) == 3
    assert done["usage"]["output_tokens"] == 7
    # persisted: user + 3 new
    listed = (await client.get(f"/sessions/{sid}/messages")).json()
    assert [m["role"] for m in listed] == ["user", "assistant", "tool", "assistant"]


async def test_stream_endpoint_releases_lock(client, monkeypatch):
    _fake_stream(monkeypatch)
    sid = await _make_session(client)
    assert (await client.post(f"/sessions/{sid}/turn/stream", json={"content": "one"})).status_code == 200
    # lock released -> a second stream works
    _fake_stream(monkeypatch)
    assert (await client.post(f"/sessions/{sid}/turn/stream", json={"content": "two"})).status_code == 200
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_turn_stream_endpoint.py -v`
Expected: FAIL(stream 路径 404 / 属性不存在)。

- [ ] **Step 3: 实现端点 + 生成器**

Edit `services/backend/src/agent_cloud_backend/api/turn.py`. Add imports (merge with existing):
```python
from fastapi.responses import StreamingResponse

from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.turn.sse import error_sse, format_sse, turn_event_to_sse
from agent_cloud_backend.turn.worker_client import run_turn_via_worker, stream_turn_via_worker
from agent_cloud_common import TurnDone
from agent_cloud_common.codec import turn_event_from_proto
```
(`run_turn_via_worker` already imported in 2d — keep; `msg_from_proto`, `common_to_content`, `build_run_turn_request`, `MessageRepository`, `SessionRepository`, `Message`, `grpc` already present.)

Add the streaming proxy generator (module-level, below the existing endpoint):
```python
async def _sse_stream(worker_endpoint: str, request, session_id: uuid.UUID):
    try:
        async for proto_event in stream_turn_via_worker(worker_endpoint, request):
            event = turn_event_from_proto(proto_event)
            if isinstance(event, TurnDone):
                message_ids = []
                async with get_sessionmaker()() as db:
                    msg_repo = MessageRepository(db)
                    for common in event.new_messages:
                        row = await msg_repo.append(
                            session_id,
                            Message(session_id=session_id, seq=0, role=common.role.value,
                                    content=common_to_content(common)),
                        )
                        message_ids.append(str(row.id))
                    await db.commit()
                yield format_sse({
                    "type": "turn_done",
                    "usage": {"input_tokens": event.usage.input_tokens,
                              "output_tokens": event.usage.output_tokens},
                    "message_ids": message_ids,
                    "stop_reason": event.stop_reason,
                })
            else:
                yield format_sse(turn_event_to_sse(event))
    except grpc.aio.AioRpcError as exc:
        yield format_sse(error_sse(exc.code()))
    finally:
        async with get_sessionmaker()() as db:
            await SessionRepository(db).release(session_id)
            await db.commit()
```

Add the endpoint (in the same router):
```python
@router.post("/stream")
async def stream_turn_endpoint(
    session_id: uuid.UUID,
    body: TurnRequest,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    session_repo = SessionRepository(db)
    s = await session_repo.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    if not await session_repo.try_acquire(session_id):
        await db.rollback()
        raise HTTPException(status_code=409, detail="session is busy")
    await db.commit()
    try:
        user_msg = await MessageRepository(db).append(
            session_id,
            Message(session_id=session_id, seq=0, role="user",
                    content={"text": body.content, "tool_calls": [], "tool_results": []}),
        )
        await db.commit()
        request = await build_run_turn_request(
            db, s, sandbox_endpoint=settings.sandbox_endpoint,
            user_message=body.content, exclude_message_id=user_msg.id,
        )
    except Exception:
        await db.rollback()
        await session_repo.release(session_id)
        await db.commit()
        raise
    return StreamingResponse(
        _sse_stream(settings.worker_endpoint, request, session_id),
        media_type="text/event-stream",
    )
```
> The existing `router = APIRouter(prefix="/sessions/{session_id}/turn", ...)` means this endpoint is `POST /sessions/{id}/turn/stream`. Keep the existing unary `@router.post("")` endpoint (2d) as-is.

- [ ] **Step 4: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_turn_stream_endpoint.py -v`
Expected: PASS(2 passed)。

- [ ] **Step 5: 提交**

```bash
git add services/backend/src/agent_cloud_backend/api/turn.py services/backend/tests/test_turn_stream_endpoint.py
git commit -m "feat(backend): add SSE streaming turn endpoint proxying worker stream"
```

---

### Task 3: 全链路 SSE e2e

**Files:**
- Test: `services/backend/tests/test_turn_stream_e2e.py`

- [ ] **Step 1: 写 e2e 测试**

Create `services/backend/tests/test_turn_stream_e2e.py`:
```python
import json

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.main import create_app
from agent_cloud_common import CompletionResult, Message, Role, ToolCall, Usage
from agent_cloud_sandbox.server import create_server as create_sandbox_server
from agent_cloud_worker.provider import FakeProvider
from agent_cloud_worker.server import create_server as create_worker_server


def _parse_sse(text: str) -> list[dict]:
    out = []
    for block in text.strip().split("\n\n"):
        line = block.strip()
        if line.startswith("data:"):
            out.append(json.loads(line[len("data:"):].strip()))
    return out


@pytest_asyncio.fixture
async def stack(engine, tmp_path):
    sandbox_server, sport = await create_sandbox_server(base_workdir=tmp_path, port=0)
    provider = FakeProvider([
        CompletionResult(message=Message(role=Role.ASSISTANT, tool_calls=[
            ToolCall(id="c1", name="write_file",
                     arguments={"path": "hi.txt", "content": "yo"})]),
            usage=Usage(input_tokens=2, output_tokens=3)),
        CompletionResult(message=Message(role=Role.ASSISTANT, text="all done"),
                         usage=Usage(input_tokens=2, output_tokens=3)),
    ])
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_session():
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_settings] = lambda: Settings(
        worker_endpoint=f"localhost:{wport}", sandbox_endpoint=f"localhost:{sport}")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, tmp_path
    await worker_server.stop(None)
    await sandbox_server.stop(None)


async def test_full_streaming_turn(stack):
    client, base = stack
    uid = (await client.post("/users", json={"email": "e2e@example.com"})).json()["id"]
    aid = (await client.post("/agent-configs",
           json={"user_id": uid, "name": "c", "model": "m", "provider": "fake"})).json()["id"]
    sid = (await client.post("/sessions", json={"user_id": uid, "agent_config_id": aid})).json()["id"]

    resp = await client.post(f"/sessions/{sid}/turn/stream", json={"content": "write it"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    kinds = [e["type"] for e in events]
    assert "tool_call_start" in kinds and "tool_result" in kinds
    assert "text_delta" in kinds            # the "all done" delta
    assert kinds[-1] == "turn_done"
    assert events[-1]["stop_reason"] == "end_turn" and len(events[-1]["message_ids"]) == 3

    # tool executed in the sandbox
    assert (base / f"sessions/{sid}" / "hi.txt").read_text() == "yo"
    # DB persisted user + assistant + tool + assistant
    listed = (await client.get(f"/sessions/{sid}/messages")).json()
    assert [m["role"] for m in listed] == ["user", "assistant", "tool", "assistant"]
```

- [ ] **Step 2: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_turn_stream_e2e.py -v`
Expected: PASS(1 passed)。需 Docker。

- [ ] **Step 3: 提交**

```bash
git add services/backend/tests/test_turn_stream_e2e.py
git commit -m "test(backend): full streaming turn e2e over SSE"
```

---

### Task 4: lint + README + 全回归

**Files:**
- Modify: `services/backend/README.md`

- [ ] **Step 1: lint**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run ruff check --fix . && uv run ruff format .`
Expected: clean。

- [ ] **Step 2: README 追加**

在 `services/backend/README.md` 的"回合编排(Plan 2d)"节后追加:
```markdown
- 流式:`POST /sessions/{id}/turn/stream` `{ "content": "..." }` → `text/event-stream`(SSE)。逐事件下发 `text_delta`/`thinking_delta`/`tool_call_start`/`tool_result`,以 `turn_done`(含 `message_ids`/`usage`/`stop_reason`)收尾;错误以 `error` 事件 in-band 下发。后端代理 worker 的 `RunTurnStream`,`turn_done` 时落库新消息并释放锁。
```

- [ ] **Step 3: 全回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/packages/common && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest -q
```
Expected:common 9;sandbox 23;worker 49;backend 50(41 + sse 6 + stream endpoint 2 + e2e 1)。

- [ ] **Step 4: 提交**

```bash
git add services/backend/README.md
git commit -m "docs(backend): document SSE streaming turn endpoint"
```

---

## Self-Review(写完后自检结果)

**Spec 覆盖(Plan 3c 范围)**:
- §6 FE↔BE SSE → `StreamingResponse(text/event-stream)` + `format_sse`。✓
- §7-② 事件下发(text_delta/thinking_delta/tool_call_start/tool_result/turn_done/error)→ `turn_event_to_sse` + 端点 turn_done/error 处理。✓
- §8 流式回合:锁 → 落 user → 组装 → 代理 worker 流 → turn_done 落库(回传 message_ids)→ 释放锁。✓
- §10 失败:worker 流错误 → in-band `error` 事件(generic,不泄露)+ finally 释放锁(全新 session,不会卡死)。✓
- 复用 2d 的锁/组装/`common_to_content`、3b 的 `RunTurnStream`/事件 codec、`MAX_GRPC_MESSAGE_BYTES`。
- 明确延后:每用户 sandbox 路由、skills、真实 provider。

**占位符扫描**:无 TBD;每步完整代码或确切命令/预期。

**关键设计点**:流式生成器用 `get_sessionmaker()` 开**全新 session** 做 turn_done 落库与锁释放(不依赖请求 DI session 在长流期间存活);前置失败(组装抛错)在返回 StreamingResponse 前释放锁;锁释放在 `finally`(成功/错误都释放)。

**类型/命名一致性**:`stream_turn_via_worker(worker_endpoint, request)` 异步生成器;`turn_event_to_sse`/`error_sse`/`format_sse`;端点 `POST /sessions/{id}/turn/stream`;复用 `turn_event_from_proto`(3b)、`build_run_turn_request`/`common_to_content`/`try_acquire`/`release`(2d)、`get_sessionmaker`(Plan 1 db.py);SSE JSON 字段与 spec §7-② 一致(tool_call_start 用 tool/args,tool_result 用 result)。
```
