import uuid
from datetime import datetime, timedelta, timezone

from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.sandbox_registry import SandboxRegistryRepository
from agent_cloud_backend.repositories.user import UserRepository


async def _user(session):
    u = await UserRepository(session).create(User(email=f"{uuid.uuid4()}@e.com"))
    await session.flush()
    return u


async def test_register_and_get_active(session):
    u = await _user(session)
    repo = SandboxRegistryRepository(session)
    sid = uuid.uuid4()
    await repo.register(sid, u.id, "localhost:1234")
    await session.commit()
    got = await repo.get_active_for_user(u.id)
    assert got is not None and got.id == sid and got.endpoint == "localhost:1234"


async def test_get_active_none_when_dead(session):
    u = await _user(session)
    repo = SandboxRegistryRepository(session)
    sid = uuid.uuid4()
    await repo.register(sid, u.id, "x")
    await session.commit()
    await repo.mark_dead(sid)
    await session.commit()
    assert await repo.get_active_for_user(u.id) is None


async def test_touch_updates_last_used(session):
    u = await _user(session)
    repo = SandboxRegistryRepository(session)
    sid = uuid.uuid4()
    sb = await repo.register(sid, u.id, "x")
    await session.commit()
    before = sb.last_used_at
    await repo.touch(sid)
    await session.commit()
    await session.refresh(sb)
    assert sb.last_used_at >= before


async def test_list_active_idle_since(session):
    u = await _user(session)
    repo = SandboxRegistryRepository(session)
    sid = uuid.uuid4()
    await repo.register(sid, u.id, "x")
    await session.commit()
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    stale = await repo.list_active_idle_since(future)  # everything is "idle since" a future cutoff
    assert sid in {s.id for s in stale}
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    assert await repo.list_active_idle_since(past) == []
