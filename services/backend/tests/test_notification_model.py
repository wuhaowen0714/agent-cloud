import uuid

from agent_cloud_backend.models.notification import Notification
from agent_cloud_backend.models.user import User


async def test_notification_row_roundtrip(session):
    u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
    session.add(u)
    await session.flush()
    n = Notification(user_id=u.id, title="喝药提醒", body="该喝药了")
    session.add(n)
    await session.commit()
    got = await session.get(Notification, n.id)
    assert got.title == "喝药提醒"
    assert got.delivered_at is None
    assert got.origin_session_id is None
    assert got.created_at is not None
