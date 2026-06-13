import uuid
from datetime import UTC, datetime, timedelta

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.scheduled_task import ScheduledTask
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.models.user import User


async def _user_agent(session) -> tuple[uuid.UUID, uuid.UUID]:
    u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
    session.add(u)
    await session.flush()
    a = AgentConfig(user_id=u.id, name="a", model="m", provider="p")
    session.add(a)
    await session.flush()
    return u.id, a.id


async def test_scheduled_task_row_roundtrip(session):
    uid, aid = await _user_agent(session)
    t = ScheduledTask(
        user_id=uid, agent_config_id=aid, name="每日新闻", prompt="总结今天的新闻",
        schedule_kind="cron", schedule_expr="0 9 * * *", schedule_tz="Asia/Shanghai",
        next_run_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(t)
    await session.commit()
    got = await session.get(ScheduledTask, t.id)
    assert got.enabled is True
    assert got.last_status is None
    assert got.running_since is None
    assert got.created_at is not None


async def test_session_has_scheduled_fields(session):
    uid, aid = await _user_agent(session)
    s = Session(user_id=uid, agent_config_id=aid, work_subdir="workspace")
    session.add(s)
    await session.commit()
    assert s.unread is False
    assert s.scheduled_task_id is None
