from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.context_document import ContextDocumentRepository
from agent_cloud_backend.repositories.memory_entry import MemoryEntryRepository
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
    assert s.work_subdir == f"sessions/{s.id}"
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


async def test_context_document_upsert(session):
    user = await _make_user(session)
    repo = ContextDocumentRepository(session)
    d1 = await repo.upsert(scope="user", type="USER", owner_id=user.id, content="v1")
    await session.commit()
    d2 = await repo.upsert(scope="user", type="USER", owner_id=user.id, content="v2")
    await session.commit()
    assert d1.id == d2.id and d2.content == "v2"


async def test_memory_append_and_list(session):
    user = await _make_user(session)
    repo = MemoryEntryRepository(session)
    await repo.append(scope="user", owner_id=user.id, content="fact1")
    await repo.append(scope="user", owner_id=user.id, content="fact2")
    await session.commit()
    entries = await repo.list_for_context(scope="user", owner_id=user.id, limit=10)
    assert {e.content for e in entries} == {"fact1", "fact2"}


async def test_memory_list_for_context_deterministic_same_transaction(session):
    """I3: appends within ONE transaction share an identical created_at
    (Postgres now() is transaction-stable), so ordering by created_at alone is
    undefined. The (created_at desc, id desc) tiebreaker must produce a
    deterministic order."""
    user = await _make_user(session)
    repo = MemoryEntryRepository(session)
    # No commit between appends -> all three rows get the same created_at.
    e1 = await repo.append(scope="user", owner_id=user.id, content="m1")
    e2 = await repo.append(scope="user", owner_id=user.id, content="m2")
    e3 = await repo.append(scope="user", owner_id=user.id, content="m3")
    await session.commit()

    # All share the same transaction timestamp -> tiebreaker is what decides.
    assert e1.created_at == e2.created_at == e3.created_at

    entries = await repo.list_for_context(scope="user", owner_id=user.id, limit=10)
    # Deterministic order defined by the id-desc tiebreaker.
    expected = sorted([e1, e2, e3], key=lambda e: e.id, reverse=True)
    assert [e.id for e in entries] == [e.id for e in expected]
