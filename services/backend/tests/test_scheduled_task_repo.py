import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.scheduled_task import ScheduledTask
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.scheduled_task import ScheduledTaskRepository
from agent_cloud_backend.repositories.session import SessionRepository
from sqlalchemy.ext.asyncio import async_sessionmaker


async def _seed(session) -> tuple[uuid.UUID, uuid.UUID]:
    u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
    session.add(u)
    await session.flush()
    a = AgentConfig(user_id=u.id, name="a", model="m", provider="p")
    session.add(a)
    await session.flush()
    return u.id, a.id


def _task(uid, aid, **kw) -> ScheduledTask:
    base = dict(
        user_id=uid,
        agent_config_id=aid,
        name="t",
        prompt="p",
        schedule_kind="interval",
        schedule_expr="600",
        schedule_tz="UTC",
    )
    base.update(kw)
    return ScheduledTask(**base)


async def test_list_by_user_scopes(session):
    uid, aid = await _seed(session)
    other, _ = await _seed(session)
    session.add(_task(uid, aid, name="mine"))
    session.add(_task(other, aid, name="theirs"))
    await session.commit()
    rows = await ScheduledTaskRepository(session).list_by_user(uid)
    assert [r.name for r in rows] == ["mine"]


async def test_select_due_only_enabled_past_and_not_running(session):
    uid, aid = await _seed(session)
    now = datetime.now(UTC)
    due = _task(uid, aid, name="due", next_run_at=now - timedelta(seconds=5))
    future = _task(uid, aid, name="future", next_run_at=now + timedelta(hours=1))
    disabled = _task(uid, aid, name="off", enabled=False, next_run_at=now - timedelta(seconds=5))
    running = _task(
        uid,
        aid,
        name="busy",
        next_run_at=now - timedelta(seconds=5),
        running_since=now - timedelta(seconds=1),
    )
    for t in (due, future, disabled, running):
        session.add(t)
    await session.commit()
    rows = await ScheduledTaskRepository(session).select_due_for_update(
        now, limit=10, run_lease_seconds=900
    )
    assert {r.name for r in rows} == {"due"}


async def test_select_due_running_lease_expired_is_reclaimed(session):
    uid, aid = await _seed(session)
    now = datetime.now(UTC)
    stale = _task(
        uid,
        aid,
        name="stale",
        next_run_at=now - timedelta(seconds=5),
        running_since=now - timedelta(seconds=1000),
    )  # > 900 lease
    session.add(stale)
    await session.commit()
    rows = await ScheduledTaskRepository(session).select_due_for_update(
        now, limit=10, run_lease_seconds=900
    )
    assert {r.name for r in rows} == {"stale"}


async def test_skip_locked_no_double_claim(engine):
    """两个并发事务对同一到期任务:SKIP LOCKED 保证只有一个拿到。"""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        uid, aid = await _seed(s)
        now = datetime.now(UTC)
        s.add(_task(uid, aid, name="solo", next_run_at=now - timedelta(seconds=5)))
        await s.commit()

    async def claim(barrier):
        async with maker() as db:
            rows = await ScheduledTaskRepository(db).select_due_for_update(
                datetime.now(UTC), limit=10, run_lease_seconds=900
            )
            await barrier.wait()  # 两个事务都进来后再各自提交,确保锁重叠
            await db.commit()
            return [r.name for r in rows]

    barrier = asyncio.Barrier(2)
    a, b = await asyncio.gather(claim(barrier), claim(barrier))
    assert sorted([len(a), len(b)]) == [0, 1]  # 一个拿到、一个被 SKIP


async def test_set_result(session):
    uid, aid = await _seed(session)
    t = _task(uid, aid, running_since=datetime.now(UTC))
    session.add(t)
    await session.commit()
    await ScheduledTaskRepository(session).set_result(
        t.id, status="ok", last_run_session_id=None, error=None, delivery_error=None
    )
    await session.commit()
    await session.refresh(t)  # 批量 UPDATE 不同步 identity map,refresh 重读
    assert t.last_status == "ok"
    assert t.running_since is None
    assert t.last_run_at is not None


async def test_session_create_for_scheduled_fields(session):
    uid, aid = await _seed(session)
    repo = SessionRepository(session)
    s = await repo.create_for(uid, aid, "title", scheduled_task_id=None, unread=True)
    await session.commit()
    assert s.unread is True
    await repo.mark_read(s.id)
    await session.commit()
    await session.refresh(s)
    assert s.unread is False
