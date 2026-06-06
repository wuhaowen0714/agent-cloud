import uuid
from datetime import UTC, datetime, timedelta

from agent_cloud_backend.models.sandbox_registry import SandboxRegistry
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.user import UserRepository
from agent_cloud_backend.sandbox.manager import SandboxManager
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker


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
        await s.execute(
            update(SandboxRegistry).values(last_used_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await s.commit()

    reaped = await mgr.reap_idle()
    assert reaped == 1
    assert len(prov.stopped) == 1
    # a new get spawns a fresh one (old is dead)
    await mgr.get_endpoint_for_user(uid)
    assert len(prov.spawned) == 2


async def test_reap_idle_failed_stop_leaves_row_reapable(engine):
    """A stop() failure for one sandbox must NOT abort the reap loop nor leak
    the row: the failing one stays ``active`` (reapable next pass), the other
    is marked ``dead``, and the return value counts only successes."""
    maker = async_sessionmaker(engine, expire_on_commit=False)

    class PartialFailProvisioner(FakeProvisioner):
        def __init__(self, fail_for: set[str]):
            super().__init__()
            self._fail_for = fail_for

        async def stop(self, sandbox_id):
            self.stopped.append(sandbox_id)
            if str(sandbox_id) in self._fail_for:
                raise RuntimeError("boom")

    # two users -> two active sandboxes (avoids the partial-unique-per-user index)
    uid_a = await _user(engine)
    uid_b = await _user(engine)

    spawn_prov = FakeProvisioner()
    mgr_spawn = SandboxManager(provisioner=spawn_prov, sessionmaker=maker, idle_ttl_seconds=1)
    await mgr_spawn.get_endpoint_for_user(uid_a)
    await mgr_spawn.get_endpoint_for_user(uid_b)
    failing_id, surviving_id = spawn_prov.spawned[0], spawn_prov.spawned[1]

    # force both idle
    async with maker() as s:
        await s.execute(
            update(SandboxRegistry).values(last_used_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await s.commit()

    prov = PartialFailProvisioner(fail_for={str(failing_id)})
    mgr = SandboxManager(provisioner=prov, sessionmaker=maker, idle_ttl_seconds=1)

    reaped = await mgr.reap_idle()  # must not raise

    assert reaped == 1  # only the successful stop counts
    assert set(prov.stopped) == {failing_id, surviving_id}  # both attempted

    async with maker() as s:
        rows = (await s.execute(select(SandboxRegistry))).scalars().all()
        status_by_id = {r.id: r.status for r in rows}
    assert status_by_id[failing_id] == "active"  # failed stop -> still reapable
    assert status_by_id[surviving_id] == "dead"  # success -> reaped

    # the still-active failing row is reapable on a subsequent pass
    prov2 = FakeProvisioner()
    mgr2 = SandboxManager(provisioner=prov2, sessionmaker=maker, idle_ttl_seconds=1)
    assert await mgr2.reap_idle() == 1
    assert prov2.stopped == [failing_id]
