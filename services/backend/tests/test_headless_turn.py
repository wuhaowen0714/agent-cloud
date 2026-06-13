import uuid

import pytest
from agent_cloud_backend.config import Settings
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.turn import headless as H
from agent_cloud_common import Message as CMessage
from agent_cloud_common import Role
from agent_cloud_common.codec import msg_to_proto
from sqlalchemy.ext.asyncio import async_sessionmaker


class _FakeConn:
    endpoint = "fake:50051"
    token = ""


class _FakeManager:
    async def get_endpoint_for_user(self, user_id):
        return _FakeConn()


class _FakeResp:
    def __init__(self, msgs):
        self.new_messages = msgs
        self.context_tokens = 123
        self.stop_reason = "end_turn"
        self.input_tokens = 10
        self.output_tokens = 5


async def _seed_session(maker) -> uuid.UUID:
    async with maker() as s:
        u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
        s.add(u)
        await s.flush()
        a = AgentConfig(user_id=u.id, name="a", model="m", provider="p")
        s.add(a)
        await s.flush()
        sess = await SessionRepository(s).create_for(u.id, a.id, "t")
        await s.commit()
        return sess.id


async def test_execute_turn_headless_persists_and_returns_final_text(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    # 重活打桩:沙箱物化/压缩 都 no-op;worker 返回一条 assistant 消息
    monkeypatch.setattr(H, "materialize_enabled_skills", lambda **k: None)

    async def _no_compact(*a, **k):
        return None

    monkeypatch.setattr(H, "maybe_compact_after_turn", _no_compact)

    async def _fake_worker(endpoint, request):
        return _FakeResp([msg_to_proto(CMessage(role=Role.ASSISTANT, text="今日要点:无新增"))])

    monkeypatch.setattr(H, "run_turn_via_worker", _fake_worker)

    sid = await _seed_session(maker)
    res = await H.execute_turn_headless(
        sid,
        "跑个任务",
        settings=Settings(_env_file=None),
        manager=_FakeManager(),
        store=object(),
    )
    assert res.final_text == "今日要点:无新增"
    assert res.stop_reason == "end_turn"
    # 锁已释放
    async with maker() as s:
        got = await SessionRepository(s).get(sid)
        assert got.status == "idle"


async def test_execute_turn_headless_busy_raises(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
        s.add(u)
        await s.flush()
        a = AgentConfig(user_id=u.id, name="a", model="m", provider="p")
        s.add(a)
        await s.flush()
        sess = await SessionRepository(s).create_for(u.id, a.id, "t")
        await SessionRepository(s).try_acquire(sess.id)  # 先占锁
        await s.commit()
        sid = sess.id
    with pytest.raises(H.SessionBusy):
        await H.execute_turn_headless(
            sid, "x", settings=Settings(_env_file=None), manager=_FakeManager(), store=object()
        )
