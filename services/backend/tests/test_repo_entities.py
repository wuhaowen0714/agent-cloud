from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.context_document import ContextDocumentRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.repositories.user import UserRepository


async def _make_user(session) -> User:
    user = await UserRepository(session).create(User(email="u@example.com"))
    await session.flush()
    return user


async def _make_agent(session, user) -> AgentConfig:
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, name="a", model="claude-x", provider="anthropic")
    )
    await session.flush()
    return agent


async def test_agent_list_by_user(session):
    user = await _make_user(session)
    await _make_agent(session, user)
    await session.commit()
    agents = await AgentConfigRepository(session).list_by_user(user.id)
    assert len(agents) == 1 and agents[0].user_id == user.id


async def test_session_default_work_subdir(session):
    user = await _make_user(session)
    agent = await _make_agent(session, user)
    repo = SessionRepository(session)
    s = await repo.create_for(user_id=user.id, agent_config_id=agent.id, title="t")
    await session.commit()
    assert s.work_subdir == "workspace"
    assert s.status == "idle"


async def test_message_seq_autoincrements(session):
    user = await _make_user(session)
    agent = await _make_agent(session, user)
    s = await SessionRepository(session).create_for(user.id, agent.id, None)
    await session.flush()
    repo = MessageRepository(session)
    m0 = await repo.append(
        s.id, Message(session_id=s.id, seq=0, role="user", content={"text": "hi"})
    )
    m1 = await repo.append(
        s.id, Message(session_id=s.id, seq=0, role="assistant", content={"text": "yo"})
    )
    await session.commit()
    assert m0.seq == 0 and m1.seq == 1
    listed = await repo.list_by_session(s.id)
    assert [m.seq for m in listed] == [0, 1]


async def test_message_seq_ordering_three_rows(session):
    """I1: appending 3+ messages assigns seq 0,1,2,... and list_by_session
    returns them in seq order."""
    user = await _make_user(session)
    agent = await _make_agent(session, user)
    s = await SessionRepository(session).create_for(user.id, agent.id, None)
    await session.flush()
    repo = MessageRepository(session)
    appended = []
    for i in range(3):
        m = await repo.append(
            s.id,
            Message(session_id=s.id, seq=0, role="user", content={"text": f"m{i}"}),
        )
        appended.append(m)
    await session.commit()

    assert [m.seq for m in appended] == [0, 1, 2]
    listed = await repo.list_by_session(s.id)
    assert [m.seq for m in listed] == [0, 1, 2]
    assert [m.content["text"] for m in listed] == ["m0", "m1", "m2"]


async def test_context_document_upsert(session):
    user = await _make_user(session)
    repo = ContextDocumentRepository(session)
    d1 = await repo.upsert(scope="user", type="USER", owner_id=user.id, content="v1")
    await session.commit()
    d2 = await repo.upsert(scope="user", type="USER", owner_id=user.id, content="v2")
    await session.commit()
    assert d1.id == d2.id and d2.content == "v2"
