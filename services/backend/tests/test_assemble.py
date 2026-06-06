from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.message import Message as OrmMessage
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.context_document import ContextDocumentRepository
from agent_cloud_backend.repositories.memory_entry import MemoryEntryRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.repositories.user import UserRepository
from agent_cloud_backend.turn.assemble import build_run_turn_request


async def test_build_request_from_db(session):
    user = await UserRepository(session).create(User(email="a@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(
        AgentConfig(
            user_id=user.id,
            name="coder",
            model="claude-x",
            provider="anthropic",
            enabled_tools=["bash"],
        )
    )
    await session.flush()
    s = await SessionRepository(session).create_for(user.id, agent.id, None)
    await session.flush()
    await ContextDocumentRepository(session).upsert("user", "USER", user.id, "# user")
    await ContextDocumentRepository(session).upsert("agent", "AGENTS", agent.id, "# agent")
    await MemoryEntryRepository(session).append("user", user.id, "likes tea")
    # history: one prior user message (NOT the current turn's)
    await MessageRepository(session).append(
        s.id, OrmMessage(session_id=s.id, seq=0, role="user", content={"text": "earlier"})
    )
    await session.commit()

    req = await build_run_turn_request(
        session,
        s,
        sandbox_endpoint="localhost:50051",
        user_message="now",
        exclude_message_id=None,
    )
    assert req.session_id == str(s.id) and req.user_id == str(user.id)
    assert req.agent.model == "claude-x" and list(req.agent.enabled_tools) == ["bash"]
    assert {d.type for d in req.documents} == {"USER", "AGENTS"}
    assert any(m.content == "likes tea" for m in req.memory)
    assert [m.text for m in req.messages] == ["earlier"]  # history
    assert req.user_message == "now"
    assert req.sandbox_endpoint == "localhost:50051"
    assert req.work_subdir == s.work_subdir


async def test_build_request_excludes_current_user_message(session):
    user = await UserRepository(session).create(User(email="b@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, name="c", model="m", provider="p")
    )
    await session.flush()
    s = await SessionRepository(session).create_for(user.id, agent.id, None)
    await session.flush()
    current = await MessageRepository(session).append(
        s.id, OrmMessage(session_id=s.id, seq=0, role="user", content={"text": "current"})
    )
    await session.commit()
    req = await build_run_turn_request(
        session,
        s,
        sandbox_endpoint="x",
        user_message="current",
        exclude_message_id=current.id,
    )
    assert req.messages == []  # the only message was excluded
