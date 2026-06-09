import uuid

import pytest
from agent_cloud_backend.models.memory_entry import MemoryEntry
from agent_cloud_backend.repositories.memory_entry import MemoryConflict, MemoryEntryRepository
from sqlalchemy import func, select


async def test_write_and_get_current(session):
    repo = MemoryEntryRepository(session)
    oid = uuid.uuid4()
    await repo.write_version("user", oid, "v1", None, expected_version=0)
    await session.commit()
    cur = await repo.get_current("user", oid)
    assert cur.content == "v1"
    assert cur.version == 1

    await repo.write_version("user", oid, "v2", None, expected_version=1)
    await session.commit()
    cur = await repo.get_current("user", oid)
    assert cur.content == "v2"
    assert cur.version == 2


async def test_get_current_none_when_absent(session):
    assert await MemoryEntryRepository(session).get_current("user", uuid.uuid4()) is None


async def test_optimistic_conflict_raises(session):
    repo = MemoryEntryRepository(session)
    oid = uuid.uuid4()
    await repo.write_version("user", oid, "v1", None, expected_version=0)
    await session.flush()
    with pytest.raises(MemoryConflict):  # 第二个写 version=1 的并发者 → 唯一约束冲突
        await repo.write_version("user", oid, "x", None, expected_version=0)


async def test_prune_keeps_latest_k(session):
    repo = MemoryEntryRepository(session)
    oid = uuid.uuid4()
    for v in range(5):
        await repo.write_version("user", oid, f"v{v + 1}", None, expected_version=v)
    await session.commit()
    removed = await repo.prune("user", oid, keep=2)
    await session.commit()
    assert removed == 3
    assert (await repo.get_current("user", oid)).version == 5  # 最新保留
    cnt = (
        await session.execute(
            select(func.count())
            .select_from(MemoryEntry)
            .where(MemoryEntry.scope == "user", MemoryEntry.owner_id == oid)
        )
    ).scalar_one()
    assert cnt == 2
