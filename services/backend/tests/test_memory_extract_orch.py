import uuid

from agent_cloud.v1 import worker_pb2
from sqlalchemy.ext.asyncio import async_sessionmaker

from agent_cloud_backend.config import Settings
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.memory_entry import MemoryEntryRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.repositories.user import UserRepository
from agent_cloud_backend.turn.memory_extract import extract_session_memory


def _settings() -> Settings:
    return Settings(_env_file=None)


def _patch_sessionmaker(monkeypatch, engine):
    import agent_cloud_backend.db as db_module

    monkeypatch.setattr(
        db_module, "_sessionmaker", async_sessionmaker(engine, expire_on_commit=False)
    )


def _patch_worker(monkeypatch, *, changed: bool, mem: str):
    calls = {"n": 0}

    async def _fake(endpoint, req):
        calls["n"] += 1
        return worker_pb2.ExtractMemoryResponse(
            user_memory=mem,
            agent_memory="",
            user_changed=changed,
            agent_changed=False,
            input_tokens=1,
            output_tokens=1,
        )

    monkeypatch.setattr(
        "agent_cloud_backend.turn.memory_extract.extract_memory_via_worker", _fake
    )
    return calls


async def _seed(engine, n_rounds: int):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        user = await UserRepository(db).create(User(email=f"{uuid.uuid4()}@e.com"))
        await db.flush()
        agent = await AgentConfigRepository(db).create(
            AgentConfig(user_id=user.id, name="a", model="m", provider="openai")
        )
        await db.flush()
        s = await SessionRepository(db).create_for(user.id, agent.id, None)
        await db.flush()
        mrepo = MessageRepository(db)
        for i in range(n_rounds):
            await mrepo.append(
                s.id, Message(session_id=s.id, seq=0, role="user", content={"text": f"u{i}"})
            )
            await mrepo.append(
                s.id, Message(session_id=s.id, seq=0, role="assistant", content={"text": f"a{i}"})
            )
        await db.commit()
        return s.id, user.id


async def _current(engine, user_id):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        return await MemoryEntryRepository(db).get_current("user", user_id)


async def _watermark(engine, sid) -> int:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        return (await db.get(Session, sid)).memory_through_seq


async def test_idle_gate_skips_when_few_rounds(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    calls = _patch_worker(monkeypatch, changed=True, mem="x")
    sid, uid = await _seed(engine, 3)  # < 10
    assert await extract_session_memory(sid, settings=_settings(), reason="idle") is False
    assert calls["n"] == 0  # 没调 worker
    assert await _current(engine, uid) is None


async def test_compaction_ignores_gate_and_writes(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    calls = _patch_worker(monkeypatch, changed=True, mem="- a fact")
    sid, uid = await _seed(engine, 2)
    assert await extract_session_memory(sid, settings=_settings(), reason="compaction") is True
    assert calls["n"] == 1
    cur = await _current(engine, uid)
    assert cur.content == "- a fact"
    assert cur.version == 1
    assert await _watermark(engine, sid) == 3  # 2 rounds → seq 0..3


async def test_idle_extracts_when_enough_rounds(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    _patch_worker(monkeypatch, changed=True, mem="- learned")
    sid, uid = await _seed(engine, 10)
    assert await extract_session_memory(sid, settings=_settings(), reason="idle") is True
    assert (await _current(engine, uid)).content == "- learned"


async def test_unchanged_no_write_but_advances_watermark(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    _patch_worker(monkeypatch, changed=False, mem="ignored")
    sid, uid = await _seed(engine, 10)
    assert await extract_session_memory(sid, settings=_settings(), reason="idle") is False
    assert await _current(engine, uid) is None  # 未写
    assert await _watermark(engine, sid) == 19  # 但水位线推进(10 rounds → max seq 19)


async def test_no_new_messages_noop(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    calls = _patch_worker(monkeypatch, changed=True, mem="x")
    sid, _ = await _seed(engine, 10)
    await extract_session_memory(sid, settings=_settings(), reason="compaction")  # 推进到 19
    n = calls["n"]
    # 第二次:没有新消息 → 不调 worker、返回 False
    assert await extract_session_memory(sid, settings=_settings(), reason="compaction") is False
    assert calls["n"] == n
