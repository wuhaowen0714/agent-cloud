# Plan 10a: Reconnectable Turns — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple turn execution from the SSE connection — a detached `Runner` task drives the turn to completion and persists regardless of client connection; clients POST to start / GET to resume (replay buffered events + live tail) via an in-process `TurnHub`; add `POST /turn/cancel`. Fixes "switch session / refresh mid-turn loses the response."

**Architecture:** `TurnHub` (module singleton) maps `session_id → ActiveTurn{events[], cond, done, task}`. A `Runner` task (`asyncio.create_task`, NOT request-scoped) consumes the worker stream into the buffer, persists on `TurnDone`, releases the lock + removes itself in `finally`. `subscribe(active)` is a replay+live generator used by both POST and GET. Spec: [2026-06-08-reconnectable-turns-design.md](../specs/2026-06-08-reconnectable-turns-design.md).

**Tech Stack:** Python 3.13, FastAPI StreamingResponse, asyncio.Condition fan-out, gRPC worker stream, pytest + testcontainer Postgres. Test exec: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest ...`.

---

## File Structure

- Create: `services/backend/src/agent_cloud_backend/turn/hub.py` — `ActiveTurn`, `TurnHub`, `get_turn_hub`, `subscribe`.
- Create: `services/backend/src/agent_cloud_backend/turn/runner.py` — `run_turn`, `_persist`, `_release_session_lock`.
- Modify: `services/backend/src/agent_cloud_backend/turn/worker_client.py` — (no change; runner calls `worker_client.stream_turn_via_worker` via the module so tests patch the source).
- Modify: `services/backend/src/agent_cloud_backend/api/turn.py` — refactor `stream_turn_endpoint` to start a runner + return `subscribe`; add `GET /stream` (resume) + `POST /cancel`; drop `_sse_stream` + the local `_release_session_lock`; fix imports.
- Modify: `services/backend/src/agent_cloud_backend/main.py` — lifespan cancels hub tasks on shutdown.
- Create: `services/backend/tests/test_turn_hub.py` — hub + subscribe (pure).
- Create: `services/backend/tests/test_turn_runner.py` — runner persists/decouples/cancels (DB + fake worker).
- Modify: `services/backend/tests/test_turn_stream_endpoint.py` — patch worker source; replace the `_sse_stream`-direct test; add GET-resume + cancel tests.

---

## Task 1: TurnHub + ActiveTurn + subscribe

**Files:** Create `turn/hub.py`; Create `tests/test_turn_hub.py`.

- [ ] **Step 1: Write the failing hub/subscribe tests**

`tests/test_turn_hub.py`:

```python
import asyncio
import uuid

import pytest
from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub, subscribe


def _sid():
    return uuid.uuid4()


async def _collect(active, out):
    async for chunk in subscribe(active):
        out.append(chunk)


async def test_hub_register_get_remove():
    hub = TurnHub()
    sid = _sid()
    assert hub.get(sid) is None
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    assert hub.get(sid) is active
    hub.remove(sid)
    assert hub.get(sid) is None


async def test_subscribe_replays_buffer_then_live_then_ends_on_done():
    active = ActiveTurn(session_id=_sid())
    await active.emit({"type": "text_delta", "text": "a"})  # buffered before subscribe
    out: list[str] = []
    task = asyncio.create_task(_collect(active, out))
    await asyncio.sleep(0)  # let it replay
    await active.emit({"type": "text_delta", "text": "b"})  # live
    await active.finish()
    await task
    joined = "".join(out)
    assert '"text":"a"' in joined.replace(" ", "")
    assert '"text":"b"' in joined.replace(" ", "")


async def test_subscribe_two_subscribers_each_get_all():
    active = ActiveTurn(session_id=_sid())
    a: list[str] = []
    b: list[str] = []
    t1 = asyncio.create_task(_collect(active, a))
    t2 = asyncio.create_task(_collect(active, b))
    await asyncio.sleep(0)
    await active.emit({"type": "x"})
    await active.finish()
    await asyncio.gather(t1, t2)
    assert len(a) == 1 and len(b) == 1


async def test_subscribe_returns_immediately_when_already_done():
    active = ActiveTurn(session_id=_sid())
    await active.emit({"type": "turn_done"})
    await active.finish()
    out: list[str] = []
    await _collect(active, out)  # should not hang
    assert len(out) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/backend && uv run pytest tests/test_turn_hub.py -q`
Expected: FAIL — `agent_cloud_backend.turn.hub` missing.

- [ ] **Step 3: Implement `turn/hub.py`**

```python
from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from agent_cloud_backend.turn.sse import format_sse


@dataclass
class ActiveTurn:
    session_id: uuid.UUID
    events: list[dict] = field(default_factory=list)
    done: bool = False
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task | None = None

    async def emit(self, event: dict) -> None:
        async with self.cond:
            self.events.append(event)
            self.cond.notify_all()

    async def finish(self) -> None:
        async with self.cond:
            self.done = True
            self.cond.notify_all()


class TurnHub:
    """进程内"正在跑的回合"注册表。一会话至多一个(由会话锁保证)。"""

    def __init__(self) -> None:
        self._turns: dict[uuid.UUID, ActiveTurn] = {}

    def get(self, session_id: uuid.UUID) -> ActiveTurn | None:
        return self._turns.get(session_id)

    def register(self, active: ActiveTurn) -> None:
        self._turns[active.session_id] = active

    def remove(self, session_id: uuid.UUID) -> None:
        self._turns.pop(session_id, None)

    def all_tasks(self) -> list[asyncio.Task]:
        return [a.task for a in self._turns.values() if a.task is not None]


_HUB = TurnHub()


def get_turn_hub() -> TurnHub:
    return _HUB


async def subscribe(active: ActiveTurn) -> AsyncIterator[str]:
    """补播已发事件 + 实时续看,直到 done 且全部吐完。多订阅者各自游标。"""
    idx = 0
    while True:
        async with active.cond:
            while idx >= len(active.events) and not active.done:
                await active.cond.wait()
            batch = active.events[idx:]
            idx = len(active.events)
            done = active.done
        for ev in batch:
            yield format_sse(ev)
        if done and idx >= len(active.events):
            return
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/backend && uv run pytest tests/test_turn_hub.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add services/backend/src/agent_cloud_backend/turn/hub.py services/backend/tests/test_turn_hub.py
git commit -m "feat(backend): TurnHub + ActiveTurn + replay/live subscribe (test-first)"
```

---

## Task 2: Runner (detached turn execution)

**Files:** Create `turn/runner.py`; Create `tests/test_turn_runner.py`.

- [ ] **Step 1: Write the failing runner tests**

`tests/test_turn_runner.py` (uses `engine` testcontainer fixture + `_make_session_row`/`_patch_global_sessionmaker` style from `test_turn_stream_endpoint.py`):

```python
import asyncio
import uuid

import pytest
from agent_cloud_common import Message, Role, TextDelta, TurnDone, Usage
from agent_cloud_common.codec import turn_event_to_proto
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker


def _patch_global_sessionmaker(monkeypatch, engine):
    import agent_cloud_backend.db as db_module
    monkeypatch.setattr(db_module, "_sessionmaker", async_sessionmaker(engine, expire_on_commit=False))


async def _make_session_row(engine):
    from agent_cloud_backend.models.agent_config import AgentConfig
    from agent_cloud_backend.models.user import User
    from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
    from agent_cloud_backend.repositories.session import SessionRepository
    from agent_cloud_backend.repositories.user import UserRepository

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        u = await UserRepository(db).create(User(email=f"{uuid.uuid4()}@e.com"))
        await db.flush()
        a = await AgentConfigRepository(db).create(AgentConfig(user_id=u.id, name="a", model="m", provider="p"))
        await db.flush()
        s = await SessionRepository(db).create_for(u.id, a.id, None)
        await db.commit()
        return s.id


async def _status(engine, sid):
    from agent_cloud_backend.models.session import Session
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        stmt = select(Session.status).where(Session.id == sid).execution_options(populate_existing=True)
        return (await db.execute(stmt)).scalar_one()


async def _roles(engine, sid):
    from agent_cloud_backend.models.message import Message as M
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        rows = (await db.execute(select(M.role).where(M.session_id == sid).order_by(M.seq))).scalars().all()
        return list(rows)


def _fake_worker(monkeypatch, gen):
    from agent_cloud_backend.turn import worker_client
    monkeypatch.setattr(worker_client, "stream_turn_via_worker", gen)


async def _acquire(engine, sid):
    from agent_cloud_backend.repositories.session import SessionRepository
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        assert await SessionRepository(db).try_acquire(sid) is True
        await db.commit()


async def test_runner_persists_and_releases_without_any_subscriber(engine, monkeypatch):
    # 核心解耦证明:没有任何订阅者,Runner 也跑完、落库、释放锁、从 Hub 移除
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)

    async def _gen(endpoint, request):
        yield turn_event_to_proto(TextDelta(text="hi"))
        yield turn_event_to_proto(TurnDone(
            new_messages=[Message(role=Role.ASSISTANT, text="done")],
            usage=Usage(input_tokens=1, output_tokens=2), stop_reason="end_turn"))
    _fake_worker(monkeypatch, _gen)

    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(hub, active, worker_endpoint="x", request=object(), session_id=sid, heartbeat_interval=999)

    assert active.done is True
    assert any(e["type"] == "turn_done" for e in active.events)
    assert await _roles(engine, sid) == ["assistant"]  # 助手消息已落库
    assert await _status(engine, sid) == "idle"  # 锁已释放
    assert hub.get(sid) is None  # 已移除


async def test_runner_cancel_emits_cancelled_and_releases(engine, monkeypatch):
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)

    async def _gen(endpoint, request):
        while True:
            yield turn_event_to_proto(TextDelta(text="x"))
            await asyncio.sleep(0.01)
    _fake_worker(monkeypatch, _gen)

    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    active.task = asyncio.create_task(run_turn(hub, active, worker_endpoint="x", request=object(), session_id=sid, heartbeat_interval=999))
    await asyncio.sleep(0.03)
    active.task.cancel()
    await active.task  # run_turn swallows the cancel, finishes cleanly

    assert active.events[-1] == {"type": "error", "message": "turn cancelled", "recoverable": False}
    assert await _status(engine, sid) == "idle"
    assert hub.get(sid) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_turn_runner.py -q`
Expected: FAIL — `agent_cloud_backend.turn.runner` missing.

- [ ] **Step 3: Implement `turn/runner.py`**

```python
from __future__ import annotations

import asyncio
import logging
import uuid

import grpc
from agent_cloud_common import TurnDone
from agent_cloud_common.codec import turn_event_from_proto

from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.turn import worker_client
from agent_cloud_backend.turn.heartbeat import session_heartbeat
from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
from agent_cloud_backend.turn.messages import common_to_content
from agent_cloud_backend.turn.sse import error_sse, turn_event_to_sse

logger = logging.getLogger(__name__)


async def _persist(session_id: uuid.UUID, new_messages) -> list[str]:
    ids: list[str] = []
    async with get_sessionmaker()() as db:
        repo = MessageRepository(db)
        for common in new_messages:
            row = await repo.append(
                session_id,
                Message(
                    session_id=session_id,
                    seq=0,
                    role=common.role.value,
                    content=common_to_content(common),
                ),
            )
            ids.append(str(row.id))
        await db.commit()
    return ids


async def _release_session_lock(session_id: uuid.UUID) -> None:
    try:
        async with get_sessionmaker()() as db:
            await SessionRepository(db).release(session_id)
            await db.commit()
    except Exception:
        logger.exception("failed to release session lock for session %s", session_id)


async def run_turn(
    hub: TurnHub,
    active: ActiveTurn,
    *,
    worker_endpoint: str,
    request,
    session_id: uuid.UUID,
    heartbeat_interval: float,
) -> None:
    """独立任务:消费 worker 流 → 缓冲 + 落库;断连不取消它(asyncio.create_task)。"""
    try:
        async with session_heartbeat(session_id, heartbeat_interval):
            async for proto_event in worker_client.stream_turn_via_worker(worker_endpoint, request):
                event = turn_event_from_proto(proto_event)
                if isinstance(event, TurnDone):
                    message_ids = await _persist(session_id, event.new_messages)
                    await active.emit(
                        {
                            "type": "turn_done",
                            "usage": {
                                "input_tokens": event.usage.input_tokens,
                                "output_tokens": event.usage.output_tokens,
                            },
                            "message_ids": message_ids,
                            "stop_reason": event.stop_reason,
                        }
                    )
                else:
                    await active.emit(turn_event_to_sse(event))
    except asyncio.CancelledError:
        # 主动取消 → 转成干净的终止事件,让 finally 收尾(不再 re-raise)
        await active.emit({"type": "error", "message": "turn cancelled", "recoverable": False})
    except grpc.aio.AioRpcError as exc:
        await active.emit(error_sse(exc.code()))
    except Exception:
        logger.exception("turn run failed for session %s", session_id)
        await active.emit({"type": "error", "message": "the turn failed", "recoverable": False})
    finally:
        await active.finish()
        await asyncio.shield(_release_session_lock(session_id))
        hub.remove(session_id)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_turn_runner.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add services/backend/src/agent_cloud_backend/turn/runner.py services/backend/tests/test_turn_runner.py
git commit -m "feat(backend): detached turn Runner (persists + releases regardless of client)"
```

---

## Task 3: Refactor endpoints (POST start / GET resume / POST cancel) + lifespan + update tests

**Files:** Modify `api/turn.py`, `main.py`, `tests/test_turn_stream_endpoint.py`.

- [ ] **Step 1: Refactor `api/turn.py`**

Replace the streaming section. Update imports — at the top, the streaming-only imports move out (`TurnDone`, `turn_event_from_proto`, `stream_turn_via_worker`, `turn_event_to_sse`, `error_sse`, `format_sse`) and add hub/runner/Response/sessionmaker:

```python
import asyncio
import logging
import uuid
from pathlib import Path

import grpc
from agent_cloud_common.codec import msg_from_proto
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.repositories.skill import AgentSkillEnableRepository
from agent_cloud_backend.sandbox.deps import get_sandbox_manager
from agent_cloud_backend.sandbox.manager import SandboxManager
from agent_cloud_backend.schemas.turn import TurnRequest, TurnResponse, TurnUsage
from agent_cloud_backend.skills.deps import get_object_store
from agent_cloud_backend.skills.materialize import materialize_enabled_skills
from agent_cloud_backend.skills.store import ObjectStore
from agent_cloud_backend.turn.assemble import build_run_turn_request
from agent_cloud_backend.turn.heartbeat import session_heartbeat
from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub, get_turn_hub, subscribe
from agent_cloud_backend.turn.messages import common_to_content
from agent_cloud_backend.turn.runner import run_turn
from agent_cloud_backend.turn.worker_client import run_turn_via_worker
```

(The non-streaming `run_turn_endpoint` at the top is UNCHANGED — it still uses `run_turn_via_worker`, `msg_from_proto`, `common_to_content`, `session_heartbeat`.)

DELETE the old `_sse_stream` function and the module-level `_release_session_lock` (both moved to / superseded by `runner.py`).

Replace `stream_turn_endpoint` and add the two new endpoints:

```python
@router.post("/stream")
async def stream_turn_endpoint(
    session_id: uuid.UUID,
    body: TurnRequest,
    settings: Settings = Depends(get_settings),
    manager: SandboxManager = Depends(get_sandbox_manager),
    store: ObjectStore = Depends(get_object_store),
    hub: TurnHub = Depends(get_turn_hub),
):
    # 用显式 DB session 做准备工作并提前关闭,避免长回合占着请求连接(订阅流不碰 DB)。
    async with get_sessionmaker()() as db:
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
                Message(
                    session_id=session_id,
                    seq=0,
                    role="user",
                    content={"text": body.content, "tool_calls": [], "tool_results": []},
                ),
            )
            await db.commit()
            sandbox_endpoint = await manager.get_endpoint_for_user(s.user_id)
            enabled_skills = await AgentSkillEnableRepository(db).list_enabled_for_agent(
                s.agent_config_id
            )
            materialize_enabled_skills(
                base_root=Path(settings.sandbox_base_root),
                user_id=s.user_id,
                work_subdir=s.work_subdir,
                skills=enabled_skills,
                store=store,
            )
            req_work_subdir = "." if settings.sandbox_provisioner == "docker" else s.work_subdir
            request = await build_run_turn_request(
                db,
                s,
                sandbox_endpoint=sandbox_endpoint,
                user_message=body.content,
                exclude_message_id=user_msg.id,
                enabled_skills=enabled_skills,
                work_subdir=req_work_subdir,
            )
        except Exception:
            await db.rollback()
            await session_repo.release(session_id)
            await db.commit()
            raise

    # DB 已关闭。起独立 Runner + 返回订阅流(补播+实时)。
    active = ActiveTurn(session_id=session_id)
    hub.register(active)
    active.task = asyncio.create_task(
        run_turn(
            hub,
            active,
            worker_endpoint=settings.worker_endpoint,
            request=request,
            session_id=session_id,
            heartbeat_interval=settings.session_heartbeat_seconds,
        )
    )
    return StreamingResponse(subscribe(active), media_type="text/event-stream")


@router.get("/stream")
async def resume_turn_endpoint(
    session_id: uuid.UUID,
    hub: TurnHub = Depends(get_turn_hub),
):
    active = hub.get(session_id)
    if active is None:
        return Response(status_code=204)
    return StreamingResponse(subscribe(active), media_type="text/event-stream")


@router.post("/cancel", status_code=204)
async def cancel_turn_endpoint(
    session_id: uuid.UUID,
    hub: TurnHub = Depends(get_turn_hub),
):
    active = hub.get(session_id)
    if active is not None and active.task is not None:
        active.task.cancel()
    return Response(status_code=204)
```

- [ ] **Step 2: Cancel hub tasks on shutdown (`main.py` lifespan)**

In the `lifespan` finally (after cancelling the reaper task), add:

```python
        from agent_cloud_backend.turn.hub import get_turn_hub

        for t in get_turn_hub().all_tasks():
            t.cancel()
```

- [ ] **Step 3: Update existing stream tests to patch the worker source + drop the `_sse_stream` test**

In `tests/test_turn_stream_endpoint.py`:

(a) Change every `_fake_stream*` helper to patch the **source module** instead of `turn_module`:

```python
def _fake_stream(monkeypatch):
    async def _gen(worker_endpoint, request):
        events = [
            TextDelta(text="hel"), TextDelta(text="lo"),
            ToolCallStarted(call_id="c1", name="bash", arguments={"command": "echo hi"}),
            ToolResultEvent(call_id="c1", content="hi\n", is_error=False),
            TurnDone(
                new_messages=[
                    Message(role=Role.ASSISTANT, text="hello"),
                    Message(role=Role.TOOL),
                    Message(role=Role.ASSISTANT, text="done"),
                ],
                usage=Usage(input_tokens=5, output_tokens=7), stop_reason="end_turn",
            ),
        ]
        for e in events:
            yield turn_event_to_proto(e)
    from agent_cloud_backend.turn import worker_client
    monkeypatch.setattr(worker_client, "stream_turn_via_worker", _gen)
```

Apply the same `worker_client`-target change to `_fake_stream_then_turn_done`, `_fake_stream_grpc_error`, and the inline `_slow_gen`/`_stream` monkeypatches (search for `monkeypatch.setattr(turn_module, "stream_turn_via_worker", ...)` → replace target with the imported `worker_client` module). The `build_run_turn_request`/`common_to_content` monkeypatches stay on `turn_module` (still defined there) **except** `common_to_content`, which now runs in the runner — patch it on `agent_cloud_backend.turn.runner` instead:

```python
    from agent_cloud_backend.turn import runner as runner_module
    monkeypatch.setattr(runner_module, "common_to_content", _boom)
```

(b) DELETE `test_sse_stream_releases_lock_on_client_disconnect` and the `_sse_stream`-direct helpers it needs (`_make_session_row`, `_read_status`) — the decouple/lock-release behavior is now covered by `test_turn_runner.py` (Task 2). The endpoint-level lock-release is still covered by `test_stream_endpoint_releases_lock`.

(c) The remaining endpoint tests (`test_stream_endpoint_emits_events_and_persists`, `_releases_lock`, `_persist_error...`, `_worker_grpc_error...`, `_concurrent...`, `_preflight_assemble_failure...`) keep working with the retargeted fakes. Note `test_preflight_assemble_failure_releases_lock` patches `turn_module.build_run_turn_request` — still valid (assembly runs in the endpoint).

- [ ] **Step 4: Add GET-resume + cancel endpoint tests**

Append to `tests/test_turn_stream_endpoint.py`:

```python
async def test_get_resume_returns_204_when_no_active_turn(client, engine, monkeypatch):
    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session(client)
    r = await client.get(f"/sessions/{sid}/turn/stream")
    assert r.status_code == 204


async def test_get_resume_replays_active_turn(client, engine, monkeypatch):
    # 起一个慢回合,趁它在跑时 GET 补播
    _patch_global_sessionmaker(monkeypatch, engine)

    async def _slow(worker_endpoint, request):
        yield turn_event_to_proto(TextDelta(text="hi"))
        await asyncio.sleep(0.3)
        yield turn_event_to_proto(TurnDone(
            new_messages=[Message(role=Role.ASSISTANT, text="done")],
            usage=Usage(input_tokens=1, output_tokens=1), stop_reason="end_turn"))
    from agent_cloud_backend.turn import worker_client
    monkeypatch.setattr(worker_client, "stream_turn_via_worker", _slow)

    sid = await _make_session(client)
    # POST 起回合(读完整个流);GET 在另一个客户端也能拿到补播
    post = asyncio.create_task(client.post(f"/sessions/{sid}/turn/stream", json={"content": "x"}))
    await asyncio.sleep(0.05)  # 让回合开始
    g = await client.get(f"/sessions/{sid}/turn/stream")
    assert g.status_code == 200
    assert "text_delta" in g.text
    await post


async def test_cancel_is_204_and_idempotent(client, engine, monkeypatch):
    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session(client)
    # 无在跑回合 → 幂等 204
    assert (await client.post(f"/sessions/{sid}/turn/cancel")).status_code == 204
```

- [ ] **Step 5: Run the turn test files + ruff**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_turn_stream_endpoint.py tests/test_turn_hub.py tests/test_turn_runner.py -q`
Expected: PASS.
Run: `uv run ruff check src/agent_cloud_backend/turn/ src/agent_cloud_backend/api/turn.py tests/test_turn_hub.py tests/test_turn_runner.py tests/test_turn_stream_endpoint.py`
Expected: clean.

- [ ] **Step 6: Full backend regression + commit**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q`
Expected: all green (watch `test_turn_stream_e2e.py` — if it also patches `turn_module.stream_turn_via_worker`, retarget it to `worker_client` too).

```bash
git add services/backend/src/agent_cloud_backend/api/turn.py services/backend/src/agent_cloud_backend/main.py services/backend/tests/test_turn_stream_endpoint.py
git commit -m "feat(backend): reconnectable turn stream (POST start / GET resume / POST cancel) via Runner+Hub"
```

---

## Self-Review

- **Spec coverage:** detached runner survives disconnect (Task 2 no-subscriber test) ✓; replay+live subscribe (Task 1) ✓; POST start + GET resume(204/replay) + POST cancel (Task 3) ✓; lock release in runner ✓; DB freed before stream ✓; lifespan cancels tasks ✓; one-per-session via lock (existing concurrent test) ✓.
- **Migration risk addressed:** existing tests patch `stream_turn_via_worker`/`common_to_content` — retargeted to the modules the runner actually uses (`worker_client`, `runner`); `_sse_stream`-direct test removed (superseded). Step 6 explicitly checks `test_turn_stream_e2e.py`.
- **Type/name consistency:** `ActiveTurn`/`TurnHub`/`subscribe`/`run_turn`/`get_turn_hub` identical across hub/runner/endpoints/tests; event dicts stored raw, `format_sse` applied only in `subscribe`.
- **No placeholders:** full code + commands + expected results per step.
- **Out of scope:** non-streaming `POST /turn` unchanged; multi-replica resume (pub/sub) deferred.
