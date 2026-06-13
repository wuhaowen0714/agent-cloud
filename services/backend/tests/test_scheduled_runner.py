import uuid
from datetime import UTC, datetime

from agent_cloud_backend.config import Settings
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.scheduled_task import ScheduledTask
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.scheduler import runner as R
from sqlalchemy.ext.asyncio import async_sessionmaker


async def _seed(maker, *, with_origin=False) -> dict:
    async with maker() as s:
        u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
        s.add(u)
        await s.flush()
        a = AgentConfig(user_id=u.id, name="a", model="m", provider="p")
        s.add(a)
        await s.flush()
        origin = None
        if with_origin:
            o = await SessionRepository(s).create_for(u.id, a.id, "chat")
            origin = o.id
        t = ScheduledTask(
            user_id=u.id,
            agent_config_id=a.id,
            name="新闻",
            prompt="总结",
            schedule_kind="interval",
            schedule_expr="600",
            schedule_tz="UTC",
            running_since=datetime.now(UTC),
            origin_session_id=origin,
        )
        s.add(t)
        await s.flush()
        await s.commit()
        return dict(
            id=t.id,
            user_id=u.id,
            agent_config_id=a.id,
            name="新闻",
            prompt="总结",
            origin_session_id=origin,
        )


def _patch_headless(monkeypatch, final_text):
    async def _fake(session_id, user_content, *, settings, manager, store, **kw):
        from agent_cloud_backend.turn.headless import HeadlessResult

        return HeadlessResult(
            new_messages=[],
            final_text=final_text,
            stop_reason="end_turn",
            input_tokens=0,
            output_tokens=0,
        )

    monkeypatch.setattr(R, "execute_turn_headless", _fake)
    monkeypatch.setattr(R, "get_sandbox_manager", lambda: object())
    monkeypatch.setattr(R, "get_object_store", lambda: object())


async def test_run_creates_unread_session_and_marks_ok(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    snap = await _seed(maker)
    _patch_headless(monkeypatch, "今天大事三件……")

    await R.run_scheduled_task(snap, Settings(_env_file=None))

    async with maker() as s:
        t = await s.get(ScheduledTask, snap["id"])
        assert t.last_status == "ok"
        assert t.running_since is None
        assert t.last_run_session_id is not None
        run = await s.get(Session, t.last_run_session_id)
        assert run.scheduled_task_id == snap["id"]
        assert run.unread is True
        assert run.title.startswith("📅 新闻")


async def test_silent_marks_skipped_and_clears_unread(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    snap = await _seed(maker)
    _patch_headless(monkeypatch, "[SILENT]")

    await R.run_scheduled_task(snap, Settings(_env_file=None))
    async with maker() as s:
        t = await s.get(ScheduledTask, snap["id"])
        assert t.last_status == "skipped"
        run = await s.get(Session, t.last_run_session_id)
        assert run.unread is False


async def test_failure_marks_error_keeps_task(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    snap = await _seed(maker)

    async def _boom(*a, **k):
        raise RuntimeError("worker down")

    monkeypatch.setattr(R, "execute_turn_headless", _boom)
    monkeypatch.setattr(R, "get_sandbox_manager", lambda: object())
    monkeypatch.setattr(R, "get_object_store", lambda: object())

    await R.run_scheduled_task(snap, Settings(_env_file=None))
    async with maker() as s:
        t = await s.get(ScheduledTask, snap["id"])
        assert t.last_status == "error"
        assert "worker down" in (t.last_error or "")


async def test_receipt_appended_to_idle_origin(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    snap = await _seed(maker, with_origin=True)
    _patch_headless(monkeypatch, "结果")

    await R.run_scheduled_task(snap, Settings(_env_file=None))
    async with maker() as s:
        msgs = await MessageRepository(s).list_by_session(snap["origin_session_id"])
        assert any("已运行" in m.content["text"] for m in msgs)
