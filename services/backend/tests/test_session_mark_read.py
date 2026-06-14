import uuid

from agent_cloud_backend.repositories.session import SessionRepository
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.conftest import register_user


async def _agent(auth_client) -> str:
    return (
        await auth_client.post("/agent-configs", json={"name": "a", "model": "m", "provider": "p"})
    ).json()["id"]


async def test_list_sessions_exposes_unread_and_scheduled(auth_client):
    aid = await _agent(auth_client)
    r = await auth_client.post("/sessions", json={"agent_config_id": aid})
    assert r.status_code == 201
    body = r.json()
    assert body["unread"] is False
    assert body["scheduled_task_id"] is None


async def test_mark_read_clears_unread(auth_client, engine):
    aid = await _agent(auth_client)
    sid = (await auth_client.post("/sessions", json={"agent_config_id": aid})).json()["id"]
    # 直接把它标为未读(模拟定时运行产物)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await SessionRepository(s).set_unread(uuid.UUID(sid), True)
        await s.commit()

    # 注册会播种一个默认会话,故按 id 取本测试创建的会话(不能假设它是列表 [0])。
    def _unread(resp):
        return {g["id"]: g["unread"] for g in resp.json()}[sid]

    assert _unread(await auth_client.get("/sessions")) is True

    r = await auth_client.post(f"/sessions/{sid}/mark-read")
    assert r.status_code == 204
    assert _unread(await auth_client.get("/sessions")) is False


async def test_mark_read_other_user_404(auth_client, client):
    aid = await _agent(auth_client)
    sid = (await auth_client.post("/sessions", json={"agent_config_id": aid})).json()["id"]
    other, _ = await register_user(client)
    r = await client.post(
        f"/sessions/{sid}/mark-read", headers={"Authorization": f"Bearer {other}"}
    )
    assert r.status_code == 404
