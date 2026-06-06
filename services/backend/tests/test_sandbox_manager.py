import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from agent_cloud_backend.models.sandbox_registry import SandboxRegistry
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.sandbox_registry import SandboxRegistryRepository
from agent_cloud_backend.repositories.user import UserRepository
from agent_cloud_backend.sandbox.manager import SandboxManager


class FakeProvisioner:
    def __init__(self):
        self.spawned: list[uuid.UUID] = []
        self.stopped: list[uuid.UUID] = []

    async def spawn(self, user_id):
        sandbox_id = uuid.uuid4()
        self.spawned.append(sandbox_id)
        return sandbox_id, f"fake:{len(self.spawned)}"

    async def stop(self, sandbox_id):
        self.stopped.append(sandbox_id)


async def _user(engine) -> uuid.UUID:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        u = await UserRepository(s).create(User(email=f"{uuid.uuid4()}@e.com"))
        await s.commit()
        return u.id


async def test_get_endpoint_spawns_then_reuses(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    prov = FakeProvisioner()
    mgr = SandboxManager(provisioner=prov, sessionmaker=maker)
    uid = await _user(engine)

    ep1 = await mgr.get_endpoint_for_user(uid)
    ep2 = await mgr.get_endpoint_for_user(uid)
    assert ep1 == ep2
    assert len(prov.spawned) == 1  # second call reused the registry entry, no new spawn


async def test_reap_idle_marks_dead_and_stops(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    prov = FakeProvisioner()
    mgr = SandboxManager(provisioner=prov, sessionmaker=maker, idle_ttl_seconds=1)
    uid = await _user(engine)
    await mgr.get_endpoint_for_user(uid)

    # force last_used_at far in the past
    async with maker() as s:
        await s.execute(update(SandboxRegistry).values(
            last_used_at=datetime.now(timezone.utc) - timedelta(hours=1)))
        await s.commit()

    reaped = await mgr.reap_idle()
    assert reaped == 1
    assert len(prov.stopped) == 1
    # a new get spawns a fresh one (old is dead)
    await mgr.get_endpoint_for_user(uid)
    assert len(prov.spawned) == 2
