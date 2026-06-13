import uuid

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.scheduled_task import ScheduledTask
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.scheduled_task import ScheduledTaskRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.turn.schedule_apply import apply_schedule_task_calls
from agent_cloud_common import Message as CMessage
from agent_cloud_common import Role, ToolCall, ToolResult
from sqlalchemy.ext.asyncio import async_sessionmaker


def _calls(args, *, ok=True, name="schedule_task", cid="c1"):
    assistant = CMessage(
        role=Role.ASSISTANT, tool_calls=[ToolCall(id=cid, name=name, arguments=args)]
    )
    tool = CMessage(
        role=Role.TOOL, tool_results=[ToolResult(call_id=cid, content="ok", is_error=not ok)]
    )
    return [assistant, tool]


async def _seed(maker, *, enabled_tools=None, scheduled=False):
    async with maker() as s:
        u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
        s.add(u)
        await s.flush()
        a = AgentConfig(
            user_id=u.id, name="a", model="m", provider="p", enabled_tools=enabled_tools or []
        )
        s.add(a)
        await s.flush()
        task_id = None
        if scheduled:
            t = ScheduledTask(
                user_id=u.id,
                agent_config_id=a.id,
                name="t",
                prompt="p",
                schedule_kind="interval",
                schedule_expr="600",
                schedule_tz="UTC",
            )
            s.add(t)
            await s.flush()
            task_id = t.id
        sess = await SessionRepository(s).create_for(u.id, a.id, "c", scheduled_task_id=task_id)
        await s.commit()
        return u.id, sess.id


GOOD = {"name": "晨报", "prompt": "总结昨日", "schedule_kind": "cron", "schedule_expr": "0 8 * * *"}


async def test_inserts_row_with_origin(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    uid, sid = await _seed(maker)
    n = await apply_schedule_task_calls(sid, _calls(GOOD))
    assert n == 1
    async with maker() as s:
        rows = await ScheduledTaskRepository(s).list_by_user(uid)
        assert len(rows) == 1
        assert rows[0].origin_session_id == sid
        assert rows[0].schedule_expr == "0 8 * * *"
        assert rows[0].next_run_at is not None


async def test_skips_error_result(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    _, sid = await _seed(maker)
    assert await apply_schedule_task_calls(sid, _calls(GOOD, ok=False)) == 0


async def test_enforces_enabled_tools(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    _, sid = await _seed(maker, enabled_tools=["bash"])  # 未含 schedule_task
    assert await apply_schedule_task_calls(sid, _calls(GOOD)) == 0


async def test_self_schedule_guard_blocks_scheduled_session(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    _, sid = await _seed(maker, scheduled=True)  # 这是定时运行产物会话
    assert await apply_schedule_task_calls(sid, _calls(GOOD)) == 0


async def test_skips_invalid_schedule(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    _, sid = await _seed(maker)
    bad = {**GOOD, "schedule_kind": "cron", "schedule_expr": "not a cron"}
    assert await apply_schedule_task_calls(sid, _calls(bad)) == 0
