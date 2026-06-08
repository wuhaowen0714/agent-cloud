# Plan 13: 回合失败的透明自动恢复 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 或 superpowers:executing-plans。步骤用 checkbox(`- [ ]`)。

**Goal:** 回合撞到可恢复失败时后端在同一回合内自动恢复重试,用户无感;只有耗尽/不可恢复才暴露错误并给正确措辞+手动重试。

**Architecture:** 纯策略模块 `turn/retry.py`(classify + RetryPolicy + decide)被两条路径复用;流式 runner 套重试循环(reassemble thunk + reset 事件),非流式 endpoint 套重试循环。前端处理 reset、真正读 `recoverable`、给手动重试按钮。

**Tech Stack:** FastAPI、grpc.aio、pytest+testcontainer;前端 React+Vitest。Spec:[2026-06-08-turn-recovery-auto-retry-design.md](../specs/2026-06-08-turn-recovery-auto-retry-design.md)。

后端测试:`cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest ...`。前端:`cd frontend && npx vitest run ...`。

## 文件结构

- **新增** `services/backend/src/agent_cloud_backend/turn/retry.py` — 纯重试策略(无 IO)。
- **新增** `services/backend/tests/test_retry.py` — 策略单测。
- **改** `config.py` — 4 个重试参数。
- **改** `turn/runner.py` — `run_turn` 加 `reassemble` 参数 + 重试循环 + reset 发射。
- **改** `api/turn.py` — 流式端点构造并传 `reassemble`;非流式端点重试循环。
- **改** 前端 `types.ts`(reset 事件)、`store.ts`(`recoverable` 字段 + `resetLive`)、`components/ChatView.tsx`(处理 reset + error 读 recoverable + onRetry)、`components/MessageList.tsx`(分支文案 + 重试按钮)。
- **改** 测试 `tests/test_turn_runner.py`、`tests/test_turn_stream_endpoint.py`、`tests/test_turn_endpoint.py`;前端 `MessageList` 测试(新增或扩充)。

说明:reset 是后端直发的控制事件(`active.emit({"type":"reset"})`),不经 `turn_event_to_sse`,故 **不改 sse.py**。reset 不截断 `ActiveTurn.events`(每订阅者游标模型下截断会错位);靠"流内 reset 标记 + 前端见到清屏"自洽,**不改 hub.py**。

---

## Task 1: 配置 + 纯策略模块 `turn/retry.py`

**Files:** `config.py`;Create `turn/retry.py`;Test `tests/test_retry.py`。

- [ ] **Step 1: config 加 4 个参数** —— `config.py`,在 compaction 参数后:
```python
    # 回合失败透明自动重试(spec: turn-recovery-auto-retry)
    turn_max_overflow_retries: int = 2  # 超窗压缩重试上限
    turn_max_transient_retries: int = 3  # 瞬时错误退避重试上限
    turn_max_total_attempts: int = 6  # 1 首发 + 两类上限之和;纯兜底
    turn_retry_backoff_base_seconds: float = 0.5  # 第 i 次重试等 base*2**i 秒,单步封顶 8s
```

- [ ] **Step 2: 失败测试** —— `tests/test_retry.py`:
```python
import grpc

from agent_cloud_backend.turn.retry import RetryAction, RetryPolicy, classify


def _policy(**kw):
    base = dict(max_overflow_retries=2, max_transient_retries=3, max_total_attempts=6, backoff_base_seconds=0.5)
    base.update(kw)
    return RetryPolicy(**base)


def test_classify():
    assert classify(grpc.StatusCode.RESOURCE_EXHAUSTED) == "overflow"
    assert classify(grpc.StatusCode.UNAVAILABLE) == "transient"
    assert classify(grpc.StatusCode.DEADLINE_EXCEEDED) == "transient"
    assert classify(grpc.StatusCode.INTERNAL) == "transient"
    assert classify(grpc.StatusCode.INVALID_ARGUMENT) == "fatal"
    assert classify(grpc.StatusCode.FAILED_PRECONDITION) == "fatal"


def test_backoff_is_exponential_and_capped():
    p = _policy(backoff_base_seconds=0.5)
    assert p.backoff_seconds(0) == 0.5
    assert p.backoff_seconds(1) == 1.0
    assert p.backoff_seconds(2) == 2.0
    assert p.backoff_seconds(10) == 8.0  # 封顶


def test_decide_overflow_retries_then_gives_up_at_cap():
    p = _policy(max_overflow_retries=2)
    code = grpc.StatusCode.RESOURCE_EXHAUSTED
    assert p.decide(code, overflow_used=0, transient_used=0, total_used=1) == RetryAction.COMPACT_RETRY
    assert p.decide(code, overflow_used=1, transient_used=0, total_used=2) == RetryAction.COMPACT_RETRY
    assert p.decide(code, overflow_used=2, transient_used=0, total_used=3) == RetryAction.GIVE_UP


def test_decide_transient_retries_then_gives_up_at_cap():
    p = _policy(max_transient_retries=3)
    code = grpc.StatusCode.UNAVAILABLE
    assert p.decide(code, overflow_used=0, transient_used=0, total_used=1) == RetryAction.BACKOFF_RETRY
    assert p.decide(code, overflow_used=0, transient_used=3, total_used=4) == RetryAction.GIVE_UP


def test_decide_fatal_never_retries():
    p = _policy()
    assert p.decide(grpc.StatusCode.INVALID_ARGUMENT, overflow_used=0, transient_used=0, total_used=1) == RetryAction.GIVE_UP


def test_decide_total_attempts_backstop():
    p = _policy(max_total_attempts=2)
    # 即便分类上限没到,total 兜底也会 GIVE_UP
    assert p.decide(grpc.StatusCode.UNAVAILABLE, overflow_used=0, transient_used=0, total_used=2) == RetryAction.GIVE_UP


def test_from_settings():
    from agent_cloud_backend.config import Settings
    p = RetryPolicy.from_settings(Settings(_env_file=None))
    assert p.max_overflow_retries == 2 and p.max_transient_retries == 3
    assert p.max_total_attempts == 6 and p.backoff_base_seconds == 0.5
```

- [ ] **Step 3: 跑 → 失败**:`cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_retry.py -q`,预期 ImportError(无 retry 模块)。

- [ ] **Step 4: 实现** —— `turn/retry.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import grpc

_TRANSIENT = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.INTERNAL,
}
_MAX_BACKOFF_SECONDS = 8.0


class RetryAction(Enum):
    COMPACT_RETRY = "compact_retry"  # 超窗:先 force_compact 再重试(进展门控在调用方)
    BACKOFF_RETRY = "backoff_retry"  # 瞬时:退避后重试同一请求
    GIVE_UP = "give_up"


def classify(code: grpc.StatusCode) -> str:
    if code == grpc.StatusCode.RESOURCE_EXHAUSTED:
        return "overflow"
    if code in _TRANSIENT:
        return "transient"
    return "fatal"


@dataclass
class RetryPolicy:
    max_overflow_retries: int
    max_transient_retries: int
    max_total_attempts: int
    backoff_base_seconds: float

    @classmethod
    def from_settings(cls, settings) -> RetryPolicy:
        return cls(
            max_overflow_retries=settings.turn_max_overflow_retries,
            max_transient_retries=settings.turn_max_transient_retries,
            max_total_attempts=settings.turn_max_total_attempts,
            backoff_base_seconds=settings.turn_retry_backoff_base_seconds,
        )

    def backoff_seconds(self, transient_index: int) -> float:
        return min(self.backoff_base_seconds * (2**transient_index), _MAX_BACKOFF_SECONDS)

    def decide(
        self,
        code: grpc.StatusCode,
        *,
        overflow_used: int,
        transient_used: int,
        total_used: int,
    ) -> RetryAction:
        # 进展门控(force_compact 是否有进展)留给调用方:本函数只看 code + 计数。
        if total_used >= self.max_total_attempts:
            return RetryAction.GIVE_UP
        kind = classify(code)
        if kind == "overflow":
            return (
                RetryAction.COMPACT_RETRY
                if overflow_used < self.max_overflow_retries
                else RetryAction.GIVE_UP
            )
        if kind == "transient":
            return (
                RetryAction.BACKOFF_RETRY
                if transient_used < self.max_transient_retries
                else RetryAction.GIVE_UP
            )
        return RetryAction.GIVE_UP
```

- [ ] **Step 5: 跑 → 通过 + ruff + 提交**:
```bash
cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_retry.py tests/test_config.py -q && uv run ruff check src/agent_cloud_backend/turn/retry.py src/agent_cloud_backend/config.py tests/test_retry.py
git add services/backend/src/agent_cloud_backend/turn/retry.py services/backend/src/agent_cloud_backend/config.py services/backend/tests/test_retry.py
git commit -m "feat(backend): turn retry policy module + config knobs"
```

---

## Task 2: 流式 runner 重试循环 + reset + reassemble

**Files:** `turn/runner.py`、`api/turn.py`(流式端点传 `reassemble`);Test `tests/test_turn_runner.py`、`tests/test_turn_stream_endpoint.py`。

- [ ] **Step 1: 失败测试(runner 级)** —— 追加到 `tests/test_turn_runner.py`。复用现有 helper(`_patch_global_sessionmaker`/`_make_session_row`/`_acquire`/`_seed_messages`/`_fake_worker`/`_summary`/`_REQ`)。`run_turn` 现需新参数 `reassemble`,所有现有调用要补上(见 Step 3 提示)。新测试:

```python
def _reassemble_stub():
    async def _r():
        return _REQ
    return _r


async def test_runner_overflow_auto_retries_with_reset(engine, monkeypatch):
    # 首次流抛 RESOURCE_EXHAUSTED → force_compact 有进展 → 发 reset → 重试成功落库。
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)
    await _seed_messages(engine, sid, 4)  # 供 force_compact(keep_recent=1)折叠

    calls = {"n": 0}

    async def _gen(endpoint, request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise grpc.aio.AioRpcError(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                initial_metadata=grpc.aio.Metadata(),
                trailing_metadata=grpc.aio.Metadata(),
            )
            yield  # pragma: no cover
        else:
            yield turn_event_to_proto(TextDelta(text="hi"))
            yield turn_event_to_proto(
                TurnDone(
                    new_messages=[Message(role=Role.ASSISTANT, text="done")],
                    usage=Usage(input_tokens=1, output_tokens=2),
                    stop_reason="end_turn",
                )
            )

    _fake_worker(monkeypatch, _gen)

    async def _fake_summarize(endpoint, req):
        return "S"

    monkeypatch.setattr("agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize)

    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=_REQ, reassemble=_reassemble_stub(),
        session_id=sid, heartbeat_interval=999, settings=Settings(),
    )

    kinds = [e["type"] for e in active.events]
    assert "reset" in kinds  # 重试前清屏
    assert any(e["type"] == "turn_done" for e in active.events)  # 重试成功
    assert calls["n"] == 2  # 失败 1 次 + 重试 1 次
    assert await _roles(engine, sid) == ["user", "assistant", "user", "assistant", "assistant"]  # 4 seed + 1 new


async def test_runner_transient_auto_retries_with_backoff(engine, monkeypatch):
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn import retry as retry_mod
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)

    # 让退避瞬时返回,避免测试等待
    monkeypatch.setattr(retry_mod.RetryPolicy, "backoff_seconds", lambda self, i: 0.0)

    calls = {"n": 0}

    async def _gen(endpoint, request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise grpc.aio.AioRpcError(
                grpc.StatusCode.UNAVAILABLE,
                initial_metadata=grpc.aio.Metadata(),
                trailing_metadata=grpc.aio.Metadata(),
            )
            yield  # pragma: no cover
        yield turn_event_to_proto(
            TurnDone(
                new_messages=[Message(role=Role.ASSISTANT, text="ok")],
                usage=Usage(input_tokens=1, output_tokens=1),
                stop_reason="end_turn",
            )
        )

    _fake_worker(monkeypatch, _gen)
    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=_REQ, reassemble=_reassemble_stub(),
        session_id=sid, heartbeat_interval=999, settings=Settings(),
    )
    assert calls["n"] == 2
    assert any(e["type"] == "turn_done" for e in active.events)


async def test_runner_transient_exhausted_recoverable_error(engine, monkeypatch):
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn import retry as retry_mod
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)
    monkeypatch.setattr(retry_mod.RetryPolicy, "backoff_seconds", lambda self, i: 0.0)

    async def _gen(endpoint, request):
        raise grpc.aio.AioRpcError(
            grpc.StatusCode.UNAVAILABLE,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
        )
        yield  # pragma: no cover

    _fake_worker(monkeypatch, _gen)
    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=_REQ, reassemble=_reassemble_stub(),
        session_id=sid, heartbeat_interval=999, settings=Settings(turn_max_transient_retries=2),
    )
    assert active.events[-1]["type"] == "error"
    assert active.events[-1]["recoverable"] is True  # 瞬时耗尽 → 可恢复
    assert await _status(engine, sid) == "idle"


async def test_runner_overflow_no_progress_non_recoverable(engine, monkeypatch):
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)
    await _seed_messages(engine, sid, 1)  # keep_recent=1 → 无可折叠 → 无进展

    async def _gen(endpoint, request):
        raise grpc.aio.AioRpcError(
            grpc.StatusCode.RESOURCE_EXHAUSTED,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
        )
        yield  # pragma: no cover

    _fake_worker(monkeypatch, _gen)

    async def _fake_summarize(endpoint, req):  # 不应被调用
        raise AssertionError("should not summarize when nothing to fold")

    monkeypatch.setattr("agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize)
    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=_REQ, reassemble=_reassemble_stub(),
        session_id=sid, heartbeat_interval=999, settings=Settings(),
    )
    assert active.events[-1]["type"] == "error"
    assert active.events[-1]["recoverable"] is False  # 无进展 → 不可恢复
```

- [ ] **Step 2: 跑 → 失败**:`TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_turn_runner.py -q`,预期现有调用 TypeError(缺 `reassemble`)/ 新测试失败。

- [ ] **Step 3: 实现 runner** —— `turn/runner.py`。加 import:
```python
from agent_cloud_backend.turn.retry import RetryAction, RetryPolicy, classify
```
把 `run_turn` 整体替换为(签名加 `reassemble`):
```python
async def run_turn(
    hub: TurnHub,
    active: ActiveTurn,
    *,
    worker_endpoint: str,
    request,
    reassemble,  # async () -> RunTurnRequest;重试时重新组装(读到压缩后的会话)
    session_id: uuid.UUID,
    heartbeat_interval: float,
    settings: Settings,
) -> None:
    """独立任务:消费 worker 流 → 落库;可恢复失败在回合内透明自动重试(spec: turn-recovery)。"""
    policy = RetryPolicy.from_settings(settings)
    overflow_used = transient_used = total_used = 0
    ctx_tokens = 0
    current = request
    try:
        async with session_heartbeat(session_id, heartbeat_interval):
            while True:
                total_used += 1
                try:
                    async for proto_event in worker_client.stream_turn_via_worker(
                        worker_endpoint, current
                    ):
                        event = turn_event_from_proto(proto_event)
                        if isinstance(event, TurnDone):
                            message_ids = await _persist(session_id, event.new_messages)
                            ctx_tokens = event.context_tokens
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
                    # 回合成功收尾 → 主动压缩(仍在心跳内)→ 结束
                    await maybe_compact_after_turn(
                        session_id, ctx_tokens, model=current.agent.model, settings=settings
                    )
                    return
                except grpc.aio.AioRpcError as exc:
                    action = policy.decide(
                        exc.code(),
                        overflow_used=overflow_used,
                        transient_used=transient_used,
                        total_used=total_used,
                    )
                    if action == RetryAction.COMPACT_RETRY:
                        progressed = await force_compact(session_id, settings=settings)
                        if not progressed:
                            # 无可折叠(仅剩最近一条仍超窗)→ 不可恢复,别让用户白重试
                            await active.emit(
                                {
                                    "type": "error",
                                    "message": "context too large to compact; please start a new session",
                                    "recoverable": False,
                                }
                            )
                            return
                        overflow_used += 1
                        await active.emit({"type": "reset"})  # 清屏 + 补播自洽(标记留在缓冲)
                        current = await reassemble()
                        continue
                    if action == RetryAction.BACKOFF_RETRY:
                        await asyncio.sleep(policy.backoff_seconds(transient_used))
                        transient_used += 1
                        await active.emit({"type": "reset"})
                        current = await reassemble()
                        continue
                    # GIVE_UP:瞬时耗尽 → error_sse(code in _RECOVERABLE → recoverable);
                    # fatal / 超窗到上限 → 同样经 error_sse(超窗在 _RECOVERABLE → 可恢复,可再试触发压缩)
                    await active.emit(error_sse(exc.code()))
                    return
    except asyncio.CancelledError:
        await active.emit({"type": "error", "message": "turn cancelled", "recoverable": False})
    except Exception:
        logger.exception("turn run failed for session %s", session_id)
        await active.emit({"type": "error", "message": "the turn failed", "recoverable": False})
    finally:
        hub.remove(session_id)
        await asyncio.shield(_finalize(active, session_id))
```
现有 runner 测试里所有 `run_turn(...)` 调用补 `reassemble=_reassemble_stub()`(共 6 处;`_reassemble_stub` 见 Step 1)。

- [ ] **Step 4: 流式端点构造 reassemble** —— `api/turn.py` `stream_turn_endpoint`。在 `request = await build_run_turn_request(...)` 之后、`except` 之前,定义闭包(注意:用新 DB session + 重新查 skills,避免跨已关闭 session 访问 ORM):
```python
            async def _reassemble():
                async with get_sessionmaker()() as rdb:
                    rs = await SessionRepository(rdb).get(session_id)
                    rskills = await AgentSkillEnableRepository(rdb).list_enabled_for_agent(
                        rs.agent_config_id
                    )
                    return await build_run_turn_request(
                        rdb,
                        rs,
                        sandbox_endpoint=sandbox_endpoint,
                        user_message=body.content,
                        exclude_message_id=user_msg.id,
                        enabled_skills=rskills,
                        work_subdir=req_work_subdir,
                    )
```
并把 `create_task(run_turn(...))` 加上 `reassemble=_reassemble`。注意 `_reassemble` 必须在 `async with get_sessionmaker()() as db:` 块**外**可用(它自己开 session);把它定义在 DB 块外、用到的变量(`session_id`/`sandbox_endpoint`/`body`/`user_msg.id`/`req_work_subdir`)都在外层作用域——确认 `user_msg`、`sandbox_endpoint`、`req_work_subdir` 在 DB 块结束后仍在作用域内(它们是普通变量,Python 函数作用域内可见)。

- [ ] **Step 5: reset 补播测试(流式端点)** —— `tests/test_turn_stream_endpoint.py` 追加:fake 首流抛 RESOURCE_EXHAUSTED、二流正常;打桩 `summarize_via_worker`;seed 历史;断言 SSE 序列里 `turn_done` 之前出现 `reset`,且最终消息落库。(参照该文件现有 `_set_worker_stream`/`_parse_sse`/`_make_session`;注意端点要 `_patch_global_sessionmaker`。seed 历史可在 `_make_session` 后用 `async_sessionmaker(engine)` 直插。)

- [ ] **Step 6: 跑 → 通过 + ruff + 提交**:
```bash
cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_turn_runner.py tests/test_turn_stream_endpoint.py -q && uv run ruff check src/ tests/
git add services/backend/src/agent_cloud_backend/turn/runner.py services/backend/src/agent_cloud_backend/api/turn.py services/backend/tests/
git commit -m "feat(backend): streaming runner transparent auto-retry (compact/backoff + reset)"
```

---

## Task 3: 非流式 endpoint 重试循环

**Files:** `api/turn.py` `run_turn_endpoint`;Test `tests/test_turn_endpoint.py`。

- [ ] **Step 1: 失败测试** —— `tests/test_turn_endpoint.py` 追加(复用 `_patch_global_sessionmaker`/`_seed_messages`/`_session_summary`):
```python
async def test_turn_overflow_auto_retries_then_200(client, engine, monkeypatch):
    _patch_global_sessionmaker(monkeypatch, engine)
    from agent_cloud_backend.api import turn as turn_module

    calls = {"n": 0}

    async def _worker(worker_endpoint, request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise grpc.aio.AioRpcError(
                code=grpc.StatusCode.RESOURCE_EXHAUSTED,
                initial_metadata=grpc.aio.Metadata(),
                trailing_metadata=grpc.aio.Metadata(),
            )
        return worker_pb2.RunTurnResponse(
            new_messages=[worker_pb2.Msg(role="assistant", text="done")],
            input_tokens=1, output_tokens=1, stop_reason="end_turn",
        )

    monkeypatch.setattr(turn_module, "run_turn_via_worker", _worker)

    async def _fake_summarize(endpoint, req):
        return "S"

    monkeypatch.setattr("agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize)
    sid = await _make_session(client)
    await _seed_messages(engine, sid, 3)
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "go"})
    assert r.status_code == 200, r.text
    assert calls["n"] == 2  # 失败 1 + 重试 1


async def test_turn_transient_auto_retries_then_200(client, engine, monkeypatch):
    _patch_global_sessionmaker(monkeypatch, engine)
    from agent_cloud_backend.api import turn as turn_module
    from agent_cloud_backend.turn import retry as retry_mod

    monkeypatch.setattr(retry_mod.RetryPolicy, "backoff_seconds", lambda self, i: 0.0)
    calls = {"n": 0}

    async def _worker(worker_endpoint, request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise grpc.aio.AioRpcError(
                code=grpc.StatusCode.UNAVAILABLE,
                initial_metadata=grpc.aio.Metadata(),
                trailing_metadata=grpc.aio.Metadata(),
            )
        return worker_pb2.RunTurnResponse(
            new_messages=[worker_pb2.Msg(role="assistant", text="ok")],
            input_tokens=1, output_tokens=1, stop_reason="end_turn",
        )

    monkeypatch.setattr(turn_module, "run_turn_via_worker", _worker)
    sid = await _make_session(client)
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "go"})
    assert r.status_code == 200, r.text
    assert calls["n"] == 2


async def test_turn_transient_exhausted_returns_503(client, engine, monkeypatch):
    _patch_global_sessionmaker(monkeypatch, engine)
    from agent_cloud_backend.api import turn as turn_module
    from agent_cloud_backend.turn import retry as retry_mod

    monkeypatch.setattr(retry_mod.RetryPolicy, "backoff_seconds", lambda self, i: 0.0)

    async def _worker(worker_endpoint, request):
        raise grpc.aio.AioRpcError(
            code=grpc.StatusCode.UNAVAILABLE,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
        )

    monkeypatch.setattr(turn_module, "run_turn_via_worker", _worker)
    sid = await _make_session(client)
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "go"})
    assert r.status_code == 503, r.text
```
(保留 Plan 12b 已有的 `test_turn_resource_exhausted_no_progress_returns_413` —— 无进展仍 413;若该测试因循环结构需要微调,改成首调 RESOURCE_EXHAUSTED、不 seed 历史、断言 413。)

- [ ] **Step 2: 跑 → 失败**(新测试断言不符)。

- [ ] **Step 3: 实现** —— `api/turn.py` `run_turn_endpoint`。加 import:
```python
from agent_cloud_backend.turn.retry import RetryAction, RetryPolicy, classify
```
把"调 worker"那段(`try: async with session_heartbeat(...): response = await run_turn_via_worker(...)` 到其 `except` 结束)替换为重试循环:
```python
        policy = RetryPolicy.from_settings(settings)
        overflow_used = transient_used = total_used = 0
        current = request
        response = None
        async with session_heartbeat(session_id, settings.session_heartbeat_seconds):
            while True:
                total_used += 1
                try:
                    response = await run_turn_via_worker(settings.worker_endpoint, current)
                    break
                except grpc.aio.AioRpcError as exc:
                    action = policy.decide(
                        exc.code(),
                        overflow_used=overflow_used,
                        transient_used=transient_used,
                        total_used=total_used,
                    )
                    if action == RetryAction.COMPACT_RETRY:
                        progressed = await force_compact(session_id, settings=settings)
                        if not progressed:
                            raise HTTPException(
                                status_code=413,
                                detail="context too large to compact; please start a new session",
                            ) from exc
                        overflow_used += 1
                        await db.refresh(s)  # 让 DI session 读到压缩后的新 summary/边界
                        current = await build_run_turn_request(
                            db, s,
                            sandbox_endpoint=sandbox_endpoint,
                            user_message=body.content,
                            exclude_message_id=user_msg.id,
                            enabled_skills=enabled_skills,
                            work_subdir=req_work_subdir,
                        )
                        continue
                    if action == RetryAction.BACKOFF_RETRY:
                        await asyncio.sleep(policy.backoff_seconds(transient_used))
                        transient_used += 1
                        continue  # 复用 current(同一请求)
                    # GIVE_UP
                    if classify(exc.code()) == "transient":
                        raise HTTPException(
                            status_code=503, detail="service unavailable, please retry"
                        ) from exc
                    raise HTTPException(
                        status_code=502, detail=f"worker unavailable: {exc.code().name}"
                    ) from exc
```
其后的"落库 + maybe_compact + return"不变(用 `response`)。确认 `asyncio` 已导入(文件顶部已有)。

- [ ] **Step 4: 跑 → 通过 + ruff + 提交**:
```bash
cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q && uv run ruff check src/ tests/
git add services/backend/src/agent_cloud_backend/api/turn.py services/backend/tests/test_turn_endpoint.py
git commit -m "feat(backend): non-streaming endpoint transparent auto-retry (compact/backoff)"
```

---

## Task 4: 前端 reset + recoverable + 手动重试

**Files:** `frontend/src/types.ts`、`store.ts`、`components/ChatView.tsx`、`components/MessageList.tsx`;Test 前端组件测试。

- [ ] **Step 1: types 加 reset 事件** —— `types.ts` 的 `TurnEvent` 联合追加:
```typescript
  | { type: "reset" }
```

- [ ] **Step 2: store 加 recoverable + resetLive** —— `store.ts`:
  - `LiveTurn` 接口加:`recoverable?: boolean`。
  - `AppState` 接口加:`resetLive: () => void`。
  - 实现:`resetLive: () => set((s) => (s.live ? { live: { ...s.live, blocks: [], status: "streaming", errorMessage: undefined } } : {})),`

- [ ] **Step 3: ChatView 处理 reset + error 读 recoverable + onRetry** —— `components/ChatView.tsx`:
  - `feed` 里加:`else if (e.type === "reset") setLive((t) => ({ ...t, blocks: [], status: "streaming", errorMessage: undefined }))`
  - error 分支改为携带 recoverable:`else if (e.type === "error") setLive((t) => ({ ...t, status: "error", errorMessage: e.message, recoverable: e.recoverable }))`
  - 新增重试处理函数:
```typescript
  const onRetry = () => {
    const t = useStore.getState().live
    if (t && t.status === "error") void onSend(t.userText)
  }
```
  - 把 `onRetry` 透传给 `<MessageList messages={messages} onRetry={onRetry} />`。

- [ ] **Step 4: MessageList 分支文案 + 重试按钮** —— `components/MessageList.tsx`:
  - 组件签名加 `onRetry?: () => void`。
  - error 显示替换为:
```tsx
            {live.status === "error" && (
              <div className="mt-1 text-xs text-red-600">
                {live.recoverable === false ? (
                  <span>⚠ {live.errorMessage ?? "回合失败"}</span>
                ) : (
                  <span>
                    ⚠ {live.errorMessage ?? "回合失败"}
                    {onRetry && (
                      <button
                        type="button"
                        onClick={onRetry}
                        className="ml-2 underline hover:text-red-800"
                      >
                        重试
                      </button>
                    )}
                  </span>
                )}
              </div>
            )}
```

- [ ] **Step 5: 前端测试** —— 在 `components/MessageList.test.tsx`(若无则新建,参照现有组件测试风格)断言:
  - `live.status==="error"` 且 `recoverable !== false` → 渲染"重试"按钮,点击调用 `onRetry`。
  - `recoverable===false` → 不渲染"重试"按钮(显示"开新会话"类文案)。
  设置 live 用 `useStore.setState({ live: {...} })`。

- [ ] **Step 6: 跑前端测试 + lint + 提交**:
```bash
cd frontend && npx vitest run src/components/MessageList.test.tsx && npm run lint 2>/dev/null || true
git add frontend/src
git commit -m "feat(frontend): handle reset event, honor recoverable, manual retry button"
```

---

## Task 5: 全量回归 + 对抗审查 + live-verify

- [ ] 后端全套:`cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q && uv run ruff check src/ tests/`;worker 套件保持绿;前端 `npx vitest run`。
- [ ] 派 Opus 子 agent 对 Plan 13 diff 做对抗审查(diff 内联),修复发现。
- [ ] live-verify:重启栈(可设小 `turn_max_*` 不必要;用打桩/真实超窗验证),或直接驱动:让 worker 偶发失败一次,确认前端无感重试 / 耗尽给重试按钮 / 超窗无进展给"开新会话"。

---

## Self-Review

- **Spec 覆盖**:策略模块(classify/RetryPolicy/decide)✓;两条路径重试循环 ✓;reset 事件 + 前端清屏 ✓;recoverable 文案分支 + 手动重试 ✓;配置 4 参数 ✓;心跳内续租 ✓;取消安全(CancelledError 不被 except AioRpcError 截、冒泡到外层)✓。
- **与 spec 的两处机制细化**:(1) reset 不截断缓冲(每订阅者游标),改为流内标记 + 前端清屏,补播自洽——不改 hub.py;(2) reset 是后端直发控制事件,不改 sse.py。两者用户可见行为与 spec 一致。
- **进展门控**:`decide` 保持纯(只看 code+计数),force_compact 的进展判定在循环里(无进展 → 不可恢复),比 spec 草案把 `compaction_progressed` 塞进 decide 更清晰。
- **类型一致**:`RetryAction`(COMPACT_RETRY/BACKOFF_RETRY/GIVE_UP)、`classify` 返回 "overflow"/"transient"/"fatal"、`backoff_seconds(i)` 在各处一致。
- **占位符**:无 TBD;新文件与函数重写给了完整代码;前端测试给了断言要点(风格参照现有,执行时对齐具体 API)。
- **边界**:超窗无进展→不可恢复(413 / recoverable:false);瞬时耗尽→503 / recoverable:true;fatal→502 / 由 _RECOVERABLE 判;退避可取消;reset 在首发(无内容)时无害。
