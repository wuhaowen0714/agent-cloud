import uuid

from agent_cloud_backend.config import Settings
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.repositories.user import UserRepository
from agent_cloud_backend.turn.title import generate_session_title
from sqlalchemy.ext.asyncio import async_sessionmaker


def _settings() -> Settings:
    return Settings(_env_file=None)


def _patch_sessionmaker(monkeypatch, engine):
    import agent_cloud_backend.db as db_module

    monkeypatch.setattr(
        db_module, "_sessionmaker", async_sessionmaker(engine, expire_on_commit=False)
    )


def _patch_worker(monkeypatch, title: str):
    calls = {"n": 0}

    async def _fake(endpoint, req):
        calls["n"] += 1
        return title

    monkeypatch.setattr("agent_cloud_backend.turn.title.generate_title_via_worker", _fake)
    return calls


async def _seed(engine, *, title: str | None = None, with_message: bool = True):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        user = await UserRepository(db).create(User(email=f"{uuid.uuid4()}@e.com"))
        await db.flush()
        agent = await AgentConfigRepository(db).create(
            AgentConfig(user_id=user.id, name="a")
        )
        await db.flush()
        s = await SessionRepository(db).create_for(user.id, agent.id, title, model="m")
        await db.flush()
        if with_message:
            await MessageRepository(db).append(
                s.id,
                Message(session_id=s.id, seq=0, role="user", content={"text": "帮我写个快排"}),
            )
        await db.commit()
        return s.id


async def _title_of(engine, sid) -> str | None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        return (await db.get(Session, sid)).title


async def test_writes_generated_title(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    calls = _patch_worker(monkeypatch, "快排实现")
    sid = await _seed(engine)
    assert await generate_session_title(sid, settings=_settings()) is True
    assert await _title_of(engine, sid) == "快排实现"
    assert calls["n"] == 1


async def test_existing_title_short_circuits_without_llm(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    calls = _patch_worker(monkeypatch, "不该出现")
    sid = await _seed(engine, title="手动名")
    assert await generate_session_title(sid, settings=_settings()) is False
    assert await _title_of(engine, sid) == "手动名"
    assert calls["n"] == 0


async def test_manual_rename_during_generation_wins(engine, monkeypatch):
    # 写前二次检查:生成期间用户手动改名 → 生成结果丢弃
    _patch_sessionmaker(monkeypatch, engine)
    sid_holder = {}

    async def _fake(endpoint, req):
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            s = await db.get(Session, sid_holder["sid"])
            s.title = "用户抢先改的名"
            await db.commit()
        return "LLM起的名"

    monkeypatch.setattr("agent_cloud_backend.turn.title.generate_title_via_worker", _fake)
    sid = await _seed(engine)
    sid_holder["sid"] = sid
    assert await generate_session_title(sid, settings=_settings()) is False
    assert await _title_of(engine, sid) == "用户抢先改的名"


async def test_worker_failure_leaves_title_null(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)

    async def _boom(endpoint, req):
        raise RuntimeError("worker down")

    monkeypatch.setattr("agent_cloud_backend.turn.title.generate_title_via_worker", _boom)
    sid = await _seed(engine)
    assert await generate_session_title(sid, settings=_settings()) is False  # 不抛
    assert await _title_of(engine, sid) is None


async def test_empty_title_from_llm_not_written(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    _patch_worker(monkeypatch, "")
    sid = await _seed(engine)
    assert await generate_session_title(sid, settings=_settings()) is False
    assert await _title_of(engine, sid) is None


async def test_session_without_user_message_skipped(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    calls = _patch_worker(monkeypatch, "不该出现")
    sid = await _seed(engine, with_message=False)
    assert await generate_session_title(sid, settings=_settings()) is False
    assert calls["n"] == 0
