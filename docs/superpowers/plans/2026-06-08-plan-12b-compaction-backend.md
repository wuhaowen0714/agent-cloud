# Plan 12b: Session Compaction — backend

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** backend orchestration of compaction — session summary fields + migration; `turn/compaction.py` (fold/summarize/persist); assemble sends `summary + post-summary messages`; turn endpoints do post-turn proactive compaction (on real `context_tokens`) and a reactive `RESOURCE_EXHAUSTED` → force-compact + retryable-error safety net. Depends on Plan 12a.

**Tech Stack:** FastAPI, SQLAlchemy/alembic, grpc.aio, pytest+testcontainer. Spec §7–11. Test: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest ...`.

---

## Task 1: session summary fields + migration

**Files:** `services/backend/src/agent_cloud_backend/models/session.py`; `services/backend/alembic/versions/<new>.py`.

- [ ] **Step 1: model** — add to `Session`:
```python
    summary: Mapped[str] = mapped_column(default="", nullable=False)
    summary_through_seq: Mapped[int] = mapped_column(default=-1, nullable=False)
```

- [ ] **Step 2: migration** — `cd services/backend && uv run alembic revision -m "session summary fields"`, then in the new version file set `down_revision` to the current head (`uv run alembic heads`) and:
```python
def upgrade() -> None:
    op.add_column("sessions", sa.Column("summary", sa.Text(), nullable=False, server_default=""))
    op.add_column("sessions", sa.Column("summary_through_seq", sa.Integer(), nullable=False, server_default="-1"))

def downgrade() -> None:
    op.drop_column("sessions", "summary_through_seq")
    op.drop_column("sessions", "summary")
```

- [ ] **Step 3: apply + verify + commit**

Run: `cd services/backend && AGENT_CLOUD_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/agent_cloud uv run alembic upgrade head` (pg must be up). Then existing model tests still pass: `TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/ -q -k "session or model" `.
```bash
git add services/backend/src/agent_cloud_backend/models/session.py services/backend/alembic/versions/
git commit -m "feat(backend): session.summary + summary_through_seq (+ migration)"
```

---

## Task 2: config + compaction module

**Files:** `config.py`; Create `turn/compaction.py`; Modify `turn/worker_client.py`; Test: `tests/test_compaction.py`.

- [ ] **Step 1: config** — add to `Settings`:
```python
    compaction_token_threshold: int = 32000  # context_tokens 超此 → 回合后压缩(模型 window 的 ~70-80%)
    compaction_keep_recent: int = 8          # 压缩时保留逐字的最近消息条数
```

- [ ] **Step 2: worker client** — add to `turn/worker_client.py`:
```python
async def summarize_via_worker(worker_endpoint: str, request: worker_pb2.SummarizeRequest) -> str:
    options = [
        ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
        ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
    ]
    async with grpc.aio.insecure_channel(worker_endpoint, options=options) as channel:
        resp = await worker_pb2_grpc.WorkerStub(channel).Summarize(request)
        return resp.summary
```

- [ ] **Step 3: failing test** for `_fold_boundary` (pure) — `tests/test_compaction.py`:
```python
from types import SimpleNamespace
from agent_cloud_backend.turn.compaction import _fold_boundary

def _m(seq): return SimpleNamespace(seq=seq)

def test_fold_boundary_keeps_recent_and_returns_boundary():
    hist = [_m(0), _m(1), _m(2), _m(3), _m(4)]  # keep_recent=2 → fold [0,1,2], boundary=2
    fold, boundary = _fold_boundary(hist, keep_recent=2)
    assert [m.seq for m in fold] == [0, 1, 2] and boundary == 2

def test_fold_boundary_none_when_not_enough():
    assert _fold_boundary([_m(0), _m(1)], keep_recent=2) is None
    assert _fold_boundary([], keep_recent=2) is None
```

- [ ] **Step 4: implement `turn/compaction.py`**:
```python
from __future__ import annotations

import logging
import uuid

from agent_cloud.v1 import worker_pb2
from agent_cloud_common.codec import msg_to_proto

from agent_cloud_backend.config import Settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.turn.messages import orm_to_common
from agent_cloud_backend.turn.worker_client import summarize_via_worker

logger = logging.getLogger(__name__)


def _fold_boundary(history_after: list, keep_recent: int):
    """保留最近 keep_recent 条,其余为待折叠。不足以折叠则 None。返回 (fold_msgs, boundary_seq)。"""
    if len(history_after) <= keep_recent:
        return None
    fold = history_after[:-keep_recent]
    return fold, fold[-1].seq


async def compact(session_id: uuid.UUID, *, worker_endpoint: str, keep_recent: int) -> bool:
    """把 summary_through_seq 之后、最近 keep_recent 条之前的历史折叠进 session.summary(增量)。"""
    async with get_sessionmaker()() as db:
        session = await SessionRepository(db).get(session_id)
        if session is None:
            return False
        agent = await AgentConfigRepository(db).get(session.agent_config_id)
        history = await MessageRepository(db).list_by_session(session_id)
        history_after = [m for m in history if m.seq > session.summary_through_seq]
        folded = _fold_boundary(history_after, keep_recent)
        if folded is None:
            return False
        fold_msgs, boundary_seq = folded
        req = worker_pb2.SummarizeRequest(
            agent=worker_pb2.Agent(
                model=agent.model, provider=agent.provider, key_ref=agent.key_ref or ""
            ),
            prior_summary=session.summary,
            messages=[msg_to_proto(orm_to_common(m)) for m in fold_msgs],
        )
        new_summary = await summarize_via_worker(worker_endpoint, req)
        session.summary = new_summary
        session.summary_through_seq = boundary_seq
        await db.commit()
        return True


async def maybe_compact_after_turn(
    session_id: uuid.UUID, context_tokens: int, *, settings: Settings
) -> None:
    """回合后主动压缩:用模型返回的真实 context_tokens 判阈值。best-effort——绝不因压缩失败坏掉已成功的回合。"""
    if context_tokens <= settings.compaction_token_threshold:
        return
    try:
        await compact(
            session_id,
            worker_endpoint=settings.worker_endpoint,
            keep_recent=settings.compaction_keep_recent,
        )
    except Exception:
        logger.exception("post-turn compaction failed for session %s", session_id)


async def force_compact(session_id: uuid.UUID, *, settings: Settings) -> None:
    """撞 400 兜底:更激进(只留最近 2 条)。best-effort。"""
    try:
        await compact(session_id, worker_endpoint=settings.worker_endpoint, keep_recent=2)
    except Exception:
        logger.exception("force compaction failed for session %s", session_id)
```

- [ ] **Step 5: run + commit**
```bash
cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_compaction.py -q && uv run ruff check src/agent_cloud_backend/turn/compaction.py tests/test_compaction.py
git add services/backend/src/agent_cloud_backend/turn/compaction.py services/backend/src/agent_cloud_backend/turn/worker_client.py services/backend/src/agent_cloud_backend/config.py services/backend/tests/test_compaction.py
git commit -m "feat(backend): compaction module (fold/summarize/persist) + config"
```

---

## Task 3: assemble sends summary + post-summary messages

**Files:** `turn/assemble.py`; Test: `tests/test_assemble.py`.

- [ ] **Step 1: failing test** — append to `test_assemble.py`: a session with `summary="早期摘要"` + `summary_through_seq=N` → request.messages excludes seq≤N and `request.history_summary == "早期摘要"`. (Use the existing DB-backed `test_build_request_from_db` style; set the session's summary fields before calling, add two messages with low/high seq.)

- [ ] **Step 2: implement** — in `build_run_turn_request`:
```python
    history = await MessageRepository(db).list_by_session(session.id)
    history = [
        m for m in history
        if m.id != exclude_message_id and m.seq > session.summary_through_seq
    ]
    history = _strip_unanswered_user_messages(history)
```
and add to the `RunTurnRequest(...)` kwargs: `history_summary=session.summary,`

- [ ] **Step 3: run + commit**
```bash
cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_assemble.py -q
git add services/backend/src/agent_cloud_backend/turn/assemble.py services/backend/tests/test_assemble.py
git commit -m "feat(backend): assemble drops summarized messages + sends history_summary"
```

---

## Task 4: turn endpoints — post-turn proactive + reactive safety net

**Files:** `turn/runner.py`, `api/turn.py`, `turn/sse.py` (the `_RECOVERABLE` set); Test: `tests/test_turn_stream_endpoint.py`, `tests/test_turn_runner.py`.

- [ ] **Step 1: `_RECOVERABLE` += RESOURCE_EXHAUSTED** — find the set (grep `_RECOVERABLE`; likely `turn/sse.py`) and add `grpc.StatusCode.RESOURCE_EXHAUSTED` so its `error_sse` is `recoverable=True`.

- [ ] **Step 2: runner (streaming) wiring** (`turn/runner.py` `run_turn`):
- Add a `settings: Settings` param (pass it from `stream_turn_endpoint`'s `create_task`).
- Capture context_tokens: in the `TurnDone` branch, after persisting, `ctx_tokens = event.context_tokens`.
- After the `async for` loop completes normally, before the `finally`: `await maybe_compact_after_turn(session_id, ctx_tokens, settings=settings)` (best-effort inside).
- In `except grpc.aio.AioRpcError as exc:` — if `exc.code() == grpc.StatusCode.RESOURCE_EXHAUSTED:` first `await force_compact(session_id, settings=settings)`, then `await active.emit(error_sse(exc.code()))` (now recoverable). (Other codes: unchanged.)

Sketch of the changed body:
```python
    ctx_tokens = 0
    try:
        async with session_heartbeat(session_id, heartbeat_interval):
            async for proto_event in worker_client.stream_turn_via_worker(worker_endpoint, request):
                event = turn_event_from_proto(proto_event)
                if isinstance(event, TurnDone):
                    message_ids = await _persist(session_id, event.new_messages)
                    ctx_tokens = event.context_tokens
                    await active.emit({...turn_done... })
                else:
                    await active.emit(turn_event_to_sse(event))
        await maybe_compact_after_turn(session_id, ctx_tokens, settings=settings)
    except asyncio.CancelledError:
        await active.emit({"type": "error", "message": "turn cancelled", "recoverable": False})
    except grpc.aio.AioRpcError as exc:
        if exc.code() == grpc.StatusCode.RESOURCE_EXHAUSTED:
            await force_compact(session_id, settings=settings)
        await active.emit(error_sse(exc.code()))
    except Exception:
        logger.exception("turn run failed for session %s", session_id)
        await active.emit({"type": "error", "message": "the turn failed", "recoverable": False})
    finally:
        hub.remove(session_id)
        await asyncio.shield(_finalize(active, session_id))
```
(`maybe_compact_after_turn` is best-effort internally, so it won't raise into the turn.) Update `stream_turn_endpoint`'s `create_task(run_turn(..., settings=settings))`.

- [ ] **Step 3: non-streaming endpoint** (`api/turn.py` `run_turn_endpoint`):
- After the persist + `await db.commit()`, add `await maybe_compact_after_turn(session_id, response.context_tokens, settings=settings)` (best-effort).
- In the `except grpc.aio.AioRpcError as exc:` (worker call) — if `exc.code() == RESOURCE_EXHAUSTED:` `await force_compact(session_id, settings=settings)` then raise `HTTPException(503, "context exceeded, compacted — please retry")` (or keep 502; the point is a retryable signal). Other codes unchanged (502).

- [ ] **Step 4: tests** — in `test_turn_stream_endpoint.py` / `test_turn_runner.py` (fake worker stream supports `context_tokens` now):
  - `test_post_turn_compaction_triggers_when_over_threshold`: monkeypatch a low `AGENT_CLOUD_COMPACTION_TOKEN_THRESHOLD` (e.g. 10); fake stream yields `TurnDone(..., context_tokens=999)`; monkeypatch `compaction.summarize_via_worker` to a stub returning "S"; after the stream, assert `session.summary` set + `summary_through_seq` advanced (needs ≥ keep_recent+1 prior messages — seed history). 
  - `test_resource_exhausted_force_compacts_and_recoverable`: fake worker stream raises `AioRpcError(RESOURCE_EXHAUSTED)`; monkeypatch `summarize_via_worker`; assert the SSE ends with `error` `recoverable: true` and `force_compact` ran (session.summary set / or summarize_via_worker called).
  - Runner-level (`test_turn_runner.py`): `maybe_compact_after_turn` called after a TurnDone with high context_tokens (assert compact ran). Keep `summarize_via_worker` faked.

- [ ] **Step 5: full backend regression + commit**
```bash
cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q && uv run ruff check src/ tests/
git add services/backend/src/agent_cloud_backend/turn/runner.py services/backend/src/agent_cloud_backend/api/turn.py services/backend/src/agent_cloud_backend/turn/sse.py services/backend/tests/
git commit -m "feat(backend): post-turn proactive compaction + RESOURCE_EXHAUSTED force-compact safety net"
```

---

## Task 5: live verify (after stack restart)

- [ ] Restart stack (so worker has Summarize + backend has the migration/endpoints). Set `AGENT_CLOUD_COMPACTION_TOKEN_THRESHOLD` low (e.g. 2000) to force it. Run several long turns in one session → check (via `psql` or an admin query) `sessions.summary` gets populated + `summary_through_seq` advances; confirm the conversation stays coherent (the agent still "remembers" earlier goals via the summary). Optionally force a context error and confirm the "请重试" recoverable path recovers.

---

## Self-Review
- Spec coverage: session fields + migration (§7) ✓; compaction module fold/summarize/persist + maybe/force (§8) ✓; assemble filter + history_summary (§9) ✓; endpoints post-turn proactive + reactive RESOURCE_EXHAUSTED→force_compact+recoverable + `_RECOVERABLE` (§10) ✓; config token threshold (§11) ✓; best-effort (compaction failure can't break the turn) ✓.
- Consistency: `maybe_compact_after_turn(context_tokens)` uses the model's real `context_tokens` (from 12a); `compact` reads/writes `summary`/`summary_through_seq`; assemble filters by the same `summary_through_seq`.
- Edge: `_fold_boundary` returns None when ≤ keep_recent (can't fold) → compact no-ops (rare: recent few messages alone exceed window; left to future, noted in spec §14).
- No placeholders for core logic; runner/endpoint shown as targeted diffs against the current (post-reconnect) structure.
