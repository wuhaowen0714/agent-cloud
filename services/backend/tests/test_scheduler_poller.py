import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from agent_cloud_backend.config import Settings
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.scheduled_task import ScheduledTask
from agent_cloud_backend.models.user import User
from agent_cloud_backend.scheduler import poller as P
from sqlalchemy.ext.asyncio import async_sessionmaker


async def _seed_task(maker, **kw) -> uuid.UUID:
    async with maker() as s:
        u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
        s.add(u)
        await s.flush()
        a = AgentConfig(user_id=u.id, name="a", model="m", provider="p")
        s.add(a)
        await s.flush()
        base = dict(
            user_id=u.id,
            agent_config_id=a.id,
            name="t",
            prompt="p",
            schedule_kind="interval",
            schedule_expr="600",
            schedule_tz="UTC",
        )
        base.update(kw)
        t = ScheduledTask(**base)
        s.add(t)
        await s.flush()
        await s.commit()
        return t.id


def _capture_runs(monkeypatch):
    ran: list[dict] = []

    async def _fake_run(snap, settings):
        ran.append(snap)

    monkeypatch.setattr(P, "run_scheduled_task", _fake_run)
    return ran


async def test_poll_advances_next_run_and_dispatches(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    ran = _capture_runs(monkeypatch)
    now = datetime.now(UTC)
    tid = await _seed_task(maker, next_run_at=now - timedelta(seconds=2))

    await P.poll_once(Settings(_env_file=None))

    assert [r["id"] for r in ran] == [tid]
    async with maker() as s:
        t = await s.get(ScheduledTask, tid)
        assert t.next_run_at > now  # 已先推进(at-most-once)
        assert t.running_since is not None  # 标记在跑


async def test_poll_fast_forwards_stale_without_running(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    ran = _capture_runs(monkeypatch)
    now = datetime.now(UTC)
    # 600s 周期、过期 5000s(远超 grace=300)→ 快进 + skipped,不执行
    tid = await _seed_task(maker, next_run_at=now - timedelta(seconds=5000))

    await P.poll_once(Settings(_env_file=None))
    assert ran == []
    async with maker() as s:
        t = await s.get(ScheduledTask, tid)
        assert t.last_status == "skipped"
        assert t.next_run_at > now


async def test_poll_once_disables_once_task(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    _capture_runs(monkeypatch)
    now = datetime.now(UTC)
    tid = await _seed_task(
        maker,
        schedule_kind="once",
        schedule_expr=(now - timedelta(seconds=2)).isoformat(),
        next_run_at=now - timedelta(seconds=2),
    )
    await P.poll_once(Settings(_env_file=None))
    async with maker() as s:
        t = await s.get(ScheduledTask, tid)
        assert t.enabled is False
        assert t.next_run_at is None


async def test_scheduler_loop_survives_poll_error(monkeypatch):
    calls = {"n": 0}
    fired = asyncio.Event()

    async def _boom(settings):
        calls["n"] += 1
        fired.set()
        raise RuntimeError("boom")

    monkeypatch.setattr(P, "poll_once", _boom)
    s = Settings(_env_file=None)
    object.__setattr__(s, "scheduler_poll_interval_seconds", 0)  # 紧循环
    task = asyncio.create_task(P.scheduler_loop(s))
    await asyncio.wait_for(fired.wait(), timeout=2)
    await asyncio.sleep(0.02)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert calls["n"] >= 2  # 抛错后仍继续
