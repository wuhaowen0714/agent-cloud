import uuid

from agent_cloud_backend.models.notification import Notification
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.conftest import register_user


async def _seed_notif(engine, user_id: str) -> str:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        n = Notification(user_id=uuid.UUID(user_id), title="喝药提醒", body="该喝药了")
        s.add(n)
        await s.commit()
        return str(n.id)


async def test_list_returns_undelivered(auth_client, engine):
    await _seed_notif(engine, auth_client.user_id)
    r = await auth_client.get("/notifications")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["title"] == "喝药提醒"


async def test_mark_delivered_clears(auth_client, engine):
    nid = await _seed_notif(engine, auth_client.user_id)
    r = await auth_client.post("/notifications/mark-delivered", json={"ids": [nid]})
    assert r.status_code == 204
    assert (await auth_client.get("/notifications")).json() == []


async def test_list_scoped_to_user(auth_client, client, engine):
    await _seed_notif(engine, auth_client.user_id)
    _other_access, other_id = await register_user(client)
    await _seed_notif(engine, other_id)
    assert len((await auth_client.get("/notifications")).json()) == 1
