import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from agent_cloud_backend.models.sandbox_registry import SandboxRegistry
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.sandbox_registry import SandboxRegistryRepository
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


async def test_concurrent_get_endpoint_single_active_row(engine):
    """Two concurrent ``get_endpoint_for_user`` for the SAME user must not
    double-spawn / split-route: the partial unique index forces exactly one
    surviving ``active`` row, both callers get the SAME endpoint, and the
    throwaway just-spawned sandbox is stopped."""
    maker = async_sessionmaker(engine, expire_on_commit=False)

    class SlowProvisioner(FakeProvisioner):
        async def spawn(self, user_id):
            await asyncio.sleep(0.05)  # widen the race window
            return await super().spawn(user_id)

    prov = SlowProvisioner()
    mgr = SandboxManager(provisioner=prov, sessionmaker=maker)
    uid = await _user(engine)

    ep1, ep2 = await asyncio.gather(
        mgr.get_endpoint_for_user(uid),
        mgr.get_endpoint_for_user(uid),
    )

    assert ep1 == ep2  # both callers routed to the same sandbox

    async with maker() as s:
        active = (
            (
                await s.execute(
                    select(SandboxRegistry).where(
                        SandboxRegistry.user_id == uid, SandboxRegistry.status == "active"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(active) == 1  # exactly one active row survives
    assert active[0].endpoint == ep1

    # both raced past the initial check so spawn fired twice, but the loser's
    # throwaway sandbox was discarded via stop()
    assert len(prov.spawned) == 2
    assert len(prov.stopped) == 1
    # the stopped one is NOT the surviving active sandbox
    assert prov.stopped[0] != active[0].id


async def test_get_active_for_user_orders_by_id_tiebreaker():
    """``get_active_for_user`` must include an ``id`` tiebreaker after
    ``created_at`` so ordering is deterministic when two rows share a
    ``created_at`` (defensive; mirrors the memory_entry convention). The partial
    unique index normally prevents >1 active row per user, so we assert the
    ORDER BY of the *actual* query the repo emits rather than inserting
    (now-illegal) duplicate active rows."""

    captured: list[str] = []

    class _CapturingSession:
        async def execute(self, stmt):
            captured.append(str(stmt).lower())

            class _R:
                def scalar_one_or_none(self_inner):
                    return None

            return _R()

    repo = SandboxRegistryRepository(_CapturingSession())  # type: ignore[arg-type]
    await repo.get_active_for_user(uuid.uuid4())

    assert captured, "repo did not issue a query"
    order_clause = captured[0].split("order by", 1)
    assert len(order_clause) == 2, "query has no ORDER BY"
    order_clause = order_clause[1]
    assert "created_at desc" in order_clause
    assert "id desc" in order_clause
    # created_at is the primary sort key, id the tiebreaker
    assert order_clause.index("created_at desc") < order_clause.index("id desc")


async def test_health_check_pass_reuses(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    prov = FakeProvisioner()

    async def always_alive(endpoint):
        return True

    mgr = SandboxManager(provisioner=prov, sessionmaker=maker, health_check=always_alive)
    uid = await _user(engine)
    ep1 = await mgr.get_endpoint_for_user(uid)
    ep2 = await mgr.get_endpoint_for_user(uid)
    assert ep1 == ep2
    assert len(prov.spawned) == 1  # alive -> reused, no respawn


async def test_health_check_fail_marks_dead_and_respawns(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    prov = FakeProvisioner()
    dead_endpoints = {"fake:1"}

    async def health(endpoint):
        return endpoint not in dead_endpoints

    mgr = SandboxManager(provisioner=prov, sessionmaker=maker, health_check=health)
    uid = await _user(engine)
    ep1 = await mgr.get_endpoint_for_user(uid)
    assert ep1 == "fake:1"
    first_id = prov.spawned[0]

    ep2 = await mgr.get_endpoint_for_user(uid)  # fake:1 探活失败 -> 重建 fake:2
    assert ep2 == "fake:2" and ep2 != ep1
    assert len(prov.spawned) == 2
    assert prov.stopped == [first_id]  # 死沙箱被尽力停掉

    async with maker() as s:
        rows = (
            (await s.execute(select(SandboxRegistry).where(SandboxRegistry.user_id == uid)))
            .scalars()
            .all()
        )
    status_by_id = {r.id: r.status for r in rows}
    assert status_by_id[first_id] == "dead"
    active = [r for r in rows if r.status == "active"]
    assert len(active) == 1 and active[0].endpoint == "fake:2"
