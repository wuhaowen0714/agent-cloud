import uuid

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.models.user import User
from agent_cloud_backend.turn.assemble import build_run_turn_request


async def _seed(session) -> Session:
    u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
    session.add(u)
    await session.flush()
    a = AgentConfig(user_id=u.id, name="a", model="m", provider="p")
    session.add(a)
    await session.flush()
    s = Session(user_id=u.id, agent_config_id=a.id, work_subdir="workspace")
    session.add(s)
    await session.flush()
    return s


async def test_is_scheduled_run_flag_defaults_false(session):
    s = await _seed(session)
    req = await build_run_turn_request(
        session, s, sandbox_endpoint="x", user_message="hi", exclude_message_id=None
    )
    assert req.is_scheduled_run is False


async def test_is_scheduled_run_flag_true(session):
    s = await _seed(session)
    req = await build_run_turn_request(
        session,
        s,
        sandbox_endpoint="x",
        user_message="hi",
        exclude_message_id=None,
        is_scheduled_run=True,
    )
    assert req.is_scheduled_run is True
