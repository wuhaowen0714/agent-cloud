import uuid

from agent_cloud_backend.models.notification import Notification
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.notification import NotificationRepository


async def _user(session) -> uuid.UUID:
    u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
    session.add(u)
    await session.flush()
    return u.id


async def test_list_undelivered_scopes_and_excludes_delivered(session):
    uid = await _user(session)
    other = await _user(session)
    session.add(Notification(user_id=uid, title="a", body="x"))
    session.add(Notification(user_id=other, title="b", body="x"))
    await session.commit()
    repo = NotificationRepository(session)
    rows = await repo.list_undelivered(uid)
    assert [r.title for r in rows] == ["a"]


async def test_mark_delivered(session):
    uid = await _user(session)
    n = Notification(user_id=uid, title="a", body="x")
    session.add(n)
    await session.commit()
    repo = NotificationRepository(session)
    await repo.mark_delivered([n.id], uid)
    await session.commit()
    assert await repo.list_undelivered(uid) == []


async def test_mark_delivered_scoped_to_owner(session):
    uid = await _user(session)
    other = await _user(session)
    n = Notification(user_id=uid, title="a", body="x")
    session.add(n)
    await session.commit()
    repo = NotificationRepository(session)
    await repo.mark_delivered([n.id], other)  # 非属主 → 不动
    await session.commit()
    assert len(await repo.list_undelivered(uid)) == 1
