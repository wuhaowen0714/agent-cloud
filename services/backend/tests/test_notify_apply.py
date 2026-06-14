import uuid

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.notification import NotificationRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.turn.notify_apply import BODY_MAX, TITLE_MAX, apply_notify_calls
from agent_cloud_common import Message as CMessage
from agent_cloud_common import Role, ToolCall, ToolResult
from sqlalchemy.ext.asyncio import async_sessionmaker


def _calls(args, *, ok=True, name="notify", cid="c1"):
    a = CMessage(role=Role.ASSISTANT, tool_calls=[ToolCall(id=cid, name=name, arguments=args)])
    t = CMessage(
        role=Role.TOOL, tool_results=[ToolResult(call_id=cid, content="ok", is_error=not ok)]
    )
    return [a, t]


async def _seed(maker, *, enabled_tools=None):
    async with maker() as s:
        u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
        s.add(u)
        await s.flush()
        a = AgentConfig(user_id=u.id, name="a", enabled_tools=enabled_tools or [])
        s.add(a)
        await s.flush()
        sess = await SessionRepository(s).create_for(u.id, a.id, "c", model="m")
        await s.commit()
        return u.id, sess.id


GOOD = {"title": "喝药提醒", "body": "该喝药了"}


async def test_inserts_notification_with_origin(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    uid, sid = await _seed(maker)
    n = await apply_notify_calls(sid, _calls(GOOD))
    assert n == 1
    async with maker() as s:
        rows = await NotificationRepository(s).list_undelivered(uid)
        assert len(rows) == 1
        assert rows[0].title == "喝药提醒"
        assert rows[0].origin_session_id == sid


async def test_skips_error_result(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    _, sid = await _seed(maker)
    assert await apply_notify_calls(sid, _calls(GOOD, ok=False)) == 0


async def test_enforces_enabled_tools(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    _, sid = await _seed(maker, enabled_tools=["bash"])
    assert await apply_notify_calls(sid, _calls(GOOD)) == 0


async def test_truncates_overlong_title_body(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    uid, sid = await _seed(maker)
    over = {"title": "T" * (TITLE_MAX + 300), "body": "B" * (BODY_MAX + 3000)}
    assert await apply_notify_calls(sid, _calls(over)) == 1
    async with maker() as s:
        rows = await NotificationRepository(s).list_undelivered(uid)
        assert len(rows[0].title) == TITLE_MAX
        assert len(rows[0].body) == BODY_MAX
