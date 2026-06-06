from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.repositories.user import UserRepository


async def _session(session):
    user = await UserRepository(session).create(User(email="l@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, name="a", model="m", provider="p")
    )
    await session.flush()
    return await SessionRepository(session).create_for(user.id, agent.id, None)


async def test_acquire_then_reject_then_release(session):
    repo = SessionRepository(session)
    s = await _session(session)
    await session.commit()

    assert await repo.try_acquire(s.id) is True
    await session.commit()
    assert (await repo.get(s.id)).status == "running"

    # second acquire while running -> rejected
    assert await repo.try_acquire(s.id) is False

    await repo.release(s.id)
    await session.commit()
    assert (await repo.get(s.id)).status == "idle"

    # acquirable again after release
    assert await repo.try_acquire(s.id) is True
