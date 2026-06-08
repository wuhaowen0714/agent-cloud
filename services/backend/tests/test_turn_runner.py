import asyncio
import uuid

import grpc
from agent_cloud_common import Message, Role, TextDelta, TurnDone, Usage
from agent_cloud_common.codec import turn_event_to_proto
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker


def _patch_global_sessionmaker(monkeypatch, engine):
    import agent_cloud_backend.db as db_module

    monkeypatch.setattr(
        db_module, "_sessionmaker", async_sessionmaker(engine, expire_on_commit=False)
    )


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
        a = await AgentConfigRepository(db).create(
            AgentConfig(user_id=u.id, name="a", model="m", provider="p")
        )
        await db.flush()
        s = await SessionRepository(db).create_for(u.id, a.id, None)
        await db.commit()
        return s.id


async def _status(engine, sid):
    from agent_cloud_backend.models.session import Session

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        stmt = (
            select(Session.status)
            .where(Session.id == sid)
            .execution_options(populate_existing=True)
        )
        return (await db.execute(stmt)).scalar_one()


async def _summary(engine, sid):
    from agent_cloud_backend.models.session import Session

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        stmt = (
            select(Session.summary, Session.summary_through_seq)
            .where(Session.id == sid)
            .execution_options(populate_existing=True)
        )
        return (await db.execute(stmt)).one()


async def _seed_messages(engine, sid, n):
    from agent_cloud_backend.models.message import Message as M
    from agent_cloud_backend.repositories.message import MessageRepository

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        for i in range(n):
            await MessageRepository(db).append(
                sid,
                M(
                    session_id=sid,
                    seq=0,
                    role="user" if i % 2 == 0 else "assistant",
                    content={"text": f"m{i}", "tool_calls": [], "tool_results": []},
                ),
            )
        await db.commit()


async def _roles(engine, sid):
    from agent_cloud_backend.models.message import Message as M

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        rows = (
            (await db.execute(select(M.role).where(M.session_id == sid).order_by(M.seq)))
            .scalars()
            .all()
        )
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
        yield turn_event_to_proto(
            TurnDone(
                new_messages=[Message(role=Role.ASSISTANT, text="done")],
                usage=Usage(input_tokens=1, output_tokens=2),
                stop_reason="end_turn",
            )
        )

    _fake_worker(monkeypatch, _gen)

    from agent_cloud_backend.config import Settings

    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=object(), session_id=sid,
        heartbeat_interval=999, settings=Settings(),
    )

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

    from agent_cloud_backend.config import Settings

    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    active.task = asyncio.create_task(
        run_turn(
            hub,
            active,
            worker_endpoint="x",
            request=object(),
            session_id=sid,
            heartbeat_interval=999,
            settings=Settings(),
        )
    )
    await asyncio.sleep(0.03)
    active.task.cancel()
    await active.task  # run_turn 吞掉 cancel,干净收尾

    assert active.events[-1] == {"type": "error", "message": "turn cancelled", "recoverable": False}
    assert await _status(engine, sid) == "idle"
    assert hub.get(sid) is None


async def test_drain_hub_releases_stranded_lock_for_never_started_runner(engine, monkeypatch):
    # I3 兜底:runner 在首次运行前就被取消 → 其 finally 从未跑 → 锁残留;drain_hub 兜底释放。
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import drain_hub

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)

    hub = TurnHub()
    hub.register(ActiveTurn(session_id=sid))  # task 留 None:模拟从未启动/无 runner 的残留
    assert await _status(engine, sid) == "running"

    await drain_hub(hub)

    assert await _status(engine, sid) == "idle"  # 锁被兜底释放
    assert hub.get(sid) is None  # 残留清掉


async def test_runner_post_turn_compaction_when_over_threshold(engine, monkeypatch):
    # 回合后 context_tokens 超阈值 → 主动压缩:session.summary 被填,summary_through_seq 推进。
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)
    # 预置 3 条历史(seq 0,1,2);回合再加 1 条 assistant(seq 3)→ 共 4;keep_recent=2 → 折叠 [0,1]
    await _seed_messages(engine, sid, 3)

    async def _gen(endpoint, request):
        yield turn_event_to_proto(
            TurnDone(
                new_messages=[Message(role=Role.ASSISTANT, text="done")],
                usage=Usage(input_tokens=1, output_tokens=2),
                stop_reason="end_turn",
                context_tokens=999,
            )
        )

    _fake_worker(monkeypatch, _gen)

    async def _fake_summarize(endpoint, req):
        return "S"

    monkeypatch.setattr(
        "agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize
    )

    settings = Settings(compaction_token_threshold=10, compaction_keep_recent=2)
    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=object(), session_id=sid,
        heartbeat_interval=999, settings=settings,
    )

    assert any(e["type"] == "turn_done" for e in active.events)  # 回合本身成功
    summary, through = await _summary(engine, sid)
    assert summary == "S"
    assert through >= 1  # 折叠边界已推进


async def test_runner_no_compaction_when_under_threshold(engine, monkeypatch):
    # context_tokens 未超阈值 → 不压缩(summarize 不被调用)。
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)
    await _seed_messages(engine, sid, 3)

    async def _gen(endpoint, request):
        yield turn_event_to_proto(
            TurnDone(
                new_messages=[Message(role=Role.ASSISTANT, text="done")],
                usage=Usage(input_tokens=1, output_tokens=2),
                stop_reason="end_turn",
                context_tokens=5,
            )
        )

    _fake_worker(monkeypatch, _gen)

    called = {"n": 0}

    async def _fake_summarize(endpoint, req):
        called["n"] += 1
        return "S"

    monkeypatch.setattr(
        "agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize
    )

    settings = Settings(compaction_token_threshold=10, compaction_keep_recent=2)
    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=object(), session_id=sid,
        heartbeat_interval=999, settings=settings,
    )

    assert called["n"] == 0  # 5 <= 10,未压缩
    summary, through = await _summary(engine, sid)
    assert summary == "" and through == -1


async def test_runner_resource_exhausted_force_compacts_and_recoverable(engine, monkeypatch):
    # worker 报 RESOURCE_EXHAUSTED(上下文超窗)→ force-compact + 末事件可恢复。
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)
    # 预置 4 条,使 force_compact(keep_recent=2)能折叠
    await _seed_messages(engine, sid, 4)

    async def _gen(endpoint, request):
        raise grpc.aio.AioRpcError(
            grpc.StatusCode.RESOURCE_EXHAUSTED,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
        )
        yield  # pragma: no cover — 使其成为 async generator

    _fake_worker(monkeypatch, _gen)

    called = {"n": 0}

    async def _fake_summarize(endpoint, req):
        called["n"] += 1
        return "FORCED"

    monkeypatch.setattr(
        "agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize
    )

    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=object(), session_id=sid,
        heartbeat_interval=999, settings=Settings(),
    )

    assert active.events[-1]["type"] == "error"
    assert active.events[-1]["recoverable"] is True  # RESOURCE_EXHAUSTED + 有进展 → 可恢复
    assert called["n"] == 1  # force_compact 跑了
    summary, _ = await _summary(engine, sid)
    assert summary == "FORCED"
    assert await _status(engine, sid) == "idle"  # 锁仍被释放


async def test_runner_resource_exhausted_no_progress_is_non_recoverable(engine, monkeypatch):
    # 仅剩最近一条仍超窗(无可折叠)→ force_compact 无进展 → 末事件不可恢复,别让用户白重试。
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)
    await _seed_messages(engine, sid, 1)  # 只有 1 条 → keep_recent=1 无法折叠

    async def _gen(endpoint, request):
        raise grpc.aio.AioRpcError(
            grpc.StatusCode.RESOURCE_EXHAUSTED,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
        )
        yield  # pragma: no cover — 使其成为 async generator

    _fake_worker(monkeypatch, _gen)

    called = {"n": 0}

    async def _fake_summarize(endpoint, req):
        called["n"] += 1
        return "X"

    monkeypatch.setattr(
        "agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize
    )

    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=object(), session_id=sid,
        heartbeat_interval=999, settings=Settings(),
    )

    assert active.events[-1]["type"] == "error"
    assert active.events[-1]["recoverable"] is False  # 无进展 → 不可恢复
    assert called["n"] == 0  # 没东西可折叠,未调 summarize
    assert await _status(engine, sid) == "idle"  # 锁仍被释放
