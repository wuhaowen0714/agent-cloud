import asyncio
import uuid

from agent_cloud_backend import db as db_module
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker


def _patch_global_sessionmaker(monkeypatch, engine):
    """端点内部 compact()/release 走全局 get_sessionmaker() → 指到测试库。"""
    monkeypatch.setattr(
        db_module, "_sessionmaker", async_sessionmaker(engine, expire_on_commit=False)
    )


async def _seed(engine, user_id, n_messages):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        agent = await AgentConfigRepository(db).create(
            AgentConfig(user_id=user_id, name="a", model="m", provider="p")
        )
        await db.flush()
        s = await SessionRepository(db).create_for(user_id, agent.id, None)
        await db.flush()
        for i in range(n_messages):
            await MessageRepository(db).append(
                s.id,
                Message(
                    session_id=s.id,
                    seq=0,  # append 内部按 max+1 重算
                    role="user" if i % 2 == 0 else "assistant",
                    content={"text": f"m{i}", "tool_calls": [], "tool_results": []},
                ),
            )
        await db.commit()
        return s.id


async def _read(engine, session_id):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        return (await db.execute(select(Session).where(Session.id == session_id))).scalar_one()


async def test_compact_unowned_returns_404(auth_client):
    r = await auth_client.post(f"/sessions/{uuid.uuid4()}/compact")
    assert r.status_code == 404


async def test_compact_busy_returns_409(auth_client, engine, monkeypatch):
    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _seed(engine, uuid.UUID(auth_client.user_id), 0)
    # 占锁:status=running、last_active_at=now(租约未过期)→ try_acquire 失败
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        await db.execute(
            update(Session)
            .where(Session.id == sid)
            .values(status="running", last_active_at=func.now())
        )
        await db.commit()
    r = await auth_client.post(f"/sessions/{sid}/compact")
    assert r.status_code == 409


async def test_compact_progress_true_and_releases(auth_client, engine, monkeypatch):
    _patch_global_sessionmaker(monkeypatch, engine)

    # compact() 会调 worker 摘要 + 提炼记忆 → 打桩,避免真 worker
    async def _fake_summarize(endpoint, req):
        return "SUMMARY"

    async def _noop_extract(session_id, *, settings, reason):
        return None

    monkeypatch.setattr("agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize)
    monkeypatch.setattr("agent_cloud_backend.turn.compaction.extract_session_memory", _noop_extract)
    sid = await _seed(engine, uuid.UUID(auth_client.user_id), 12)  # > keep_recent(8)

    r = await auth_client.post(f"/sessions/{sid}/compact")
    assert r.status_code == 200
    assert r.json() == {"compacted": True}

    s = await _read(engine, sid)
    assert s.summary_through_seq > -1  # 边界推进了
    assert s.status == "idle"  # 锁已释放


async def test_compact_nothing_to_compact_returns_false(auth_client, engine, monkeypatch):
    _patch_global_sessionmaker(monkeypatch, engine)

    async def _noop_extract(session_id, *, settings, reason):
        return None

    monkeypatch.setattr("agent_cloud_backend.turn.compaction.extract_session_memory", _noop_extract)
    sid = await _seed(engine, uuid.UUID(auth_client.user_id), 2)  # < keep_recent → 无可折叠

    r = await auth_client.post(f"/sessions/{sid}/compact")
    assert r.status_code == 200
    assert r.json() == {"compacted": False}
    assert (await _read(engine, sid)).status == "idle"


async def test_compact_holds_lock_during_run(auth_client, engine, monkeypatch):
    """压缩进行中(worker 调用未返回)会话锁必须被持有 → 并发 try_acquire 失败。

    这正是 C1 的核心安全属性:压缩与回合互斥。配合 session_heartbeat,长压缩也不会
    被并发回合抢锁(心跳机制本身由 test_session_lock 覆盖)。
    """
    _patch_global_sessionmaker(monkeypatch, engine)
    started = asyncio.Event()
    gate = asyncio.Event()

    async def _slow_summarize(endpoint, req):
        started.set()
        await gate.wait()  # 卡住,模拟慢 worker
        return "SUMMARY"

    async def _noop_extract(session_id, *, settings, reason):
        return None

    monkeypatch.setattr("agent_cloud_backend.turn.compaction.summarize_via_worker", _slow_summarize)
    monkeypatch.setattr("agent_cloud_backend.turn.compaction.extract_session_memory", _noop_extract)
    sid = await _seed(engine, uuid.UUID(auth_client.user_id), 12)

    task = asyncio.create_task(auth_client.post(f"/sessions/{sid}/compact"))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        # 压缩卡在 worker 调用里 → 锁被持有 → 并发抢锁应失败
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            assert await SessionRepository(db).try_acquire(sid) is False
            await db.commit()
    finally:
        gate.set()
    r = await task
    assert r.status_code == 200
    assert (await _read(engine, sid)).status == "idle"  # 收尾释放
