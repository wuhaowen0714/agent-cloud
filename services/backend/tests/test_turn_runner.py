import asyncio
import uuid

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

    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=object(), session_id=sid, heartbeat_interval=999
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
