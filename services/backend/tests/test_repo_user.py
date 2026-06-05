import uuid

from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.user import UserRepository


async def test_create_and_get_user(session):
    repo = UserRepository(session)
    user = await repo.create(User(email="a@example.com"))
    await session.commit()

    fetched = await repo.get(user.id)
    assert fetched is not None
    assert fetched.email == "a@example.com"


async def test_get_missing_returns_none(session):
    repo = UserRepository(session)
    assert await repo.get(uuid.uuid4()) is None


async def test_list_users(session):
    repo = UserRepository(session)
    await repo.create(User(email="a@example.com"))
    await repo.create(User(email="b@example.com"))
    await session.commit()
    users = await repo.list()
    assert {u.email for u in users} == {"a@example.com", "b@example.com"}
