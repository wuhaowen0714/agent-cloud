from datetime import UTC, datetime, timedelta

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.repositories.user import UserRepository
from sqlalchemy import select, update


async def _force_running(session, session_id, last_active_at):
    """Directly set status=running with a chosen last_active_at, bypassing the repo."""
    await session.execute(
        update(Session)
        .where(Session.id == session_id)
        .values(status="running", last_active_at=last_active_at)
    )
    await session.commit()


async def _read(session, session_id) -> Session:
    """Read a fresh row, bypassing the identity-map cache."""
    stmt = (
        select(Session)
        .where(Session.id == session_id)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalar_one()


async def _session(session):
    user = await UserRepository(session).create(User(email="l@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, name="a", model="m", provider="p")
    )
    await session.flush()
    return await SessionRepository(session).create_for(user.id, agent.id, None)


async def test_acquire_then_reject_then_release(session):
    repo = SessionRepository(session)
    s = await _session(session)
    await session.commit()

    assert await repo.try_acquire(s.id) is True
    await session.commit()
    assert (await repo.get(s.id)).status == "running"

    # second acquire while running -> rejected
    assert await repo.try_acquire(s.id) is False

    await repo.release(s.id)
    await session.commit()
    assert (await repo.get(s.id)).status == "idle"

    # acquirable again after release
    assert await repo.try_acquire(s.id) is True


# --- I1: stale-lock takeover (crash recovery) ---


async def test_stale_running_lock_can_be_taken_over(session):
    repo = SessionRepository(session)
    s = await _session(session)
    sid = s.id
    await session.commit()

    # simulate a crashed request: running, but last_active_at is an hour ago
    stale = datetime.now(UTC) - timedelta(hours=1)
    await _force_running(session, sid, stale)

    # takeover: lease expired, so acquire succeeds
    assert await repo.try_acquire(sid) is True
    await session.commit()

    refreshed = await _read(session, sid)
    assert refreshed.status == "running"
    # last_active_at was refreshed to ~now (well after the stale timestamp)
    assert refreshed.last_active_at > stale + timedelta(minutes=30)


async def test_fresh_running_lock_is_not_taken_over(session):
    repo = SessionRepository(session)
    s = await _session(session)
    sid = s.id
    await session.commit()

    # a live request: running with a recent last_active_at
    recent = datetime.now(UTC) - timedelta(seconds=5)
    await _force_running(session, sid, recent)

    # within the lease window -> rejected
    assert await repo.try_acquire(sid) is False
