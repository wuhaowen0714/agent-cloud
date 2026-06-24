"""分组清除:POST /sessions/bulk-delete 批量删会话(校验所有权、跳过 busy)。"""

import uuid

from agent_cloud_backend.repositories.session import SessionRepository
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.conftest import register_user


async def _agent(auth_client) -> str:
    return (
        await auth_client.post("/agent-configs", json={"name": "a", "model": "m", "provider": "p"})
    ).json()["id"]


async def _session(auth_client, aid) -> str:
    return (await auth_client.post("/sessions", json={"agent_config_id": aid})).json()["id"]


async def test_bulk_delete_removes_idle_sessions(auth_client):
    aid = await _agent(auth_client)
    s1 = await _session(auth_client, aid)
    s2 = await _session(auth_client, aid)
    r = await auth_client.post("/sessions/bulk-delete", json={"session_ids": [s1, s2]})
    assert r.status_code == 200
    assert r.json() == {"deleted": 2, "skipped": []}
    ids = {g["id"] for g in (await auth_client.get("/sessions")).json()}
    assert s1 not in ids and s2 not in ids


async def test_bulk_delete_skips_running(auth_client, engine):
    aid = await _agent(auth_client)
    s1 = await _session(auth_client, aid)
    s2 = await _session(auth_client, aid)
    # 把 s2 置为 running(模拟回合进行中):try_acquire 抢锁
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        assert await SessionRepository(s).try_acquire(uuid.UUID(s2))
        await s.commit()
    r = await auth_client.post("/sessions/bulk-delete", json={"session_ids": [s1, s2]})
    assert r.json() == {"deleted": 1, "skipped": [s2]}  # s1 删、s2 在跑跳过(返回其 id)
    ids = {g["id"] for g in (await auth_client.get("/sessions")).json()}
    assert s1 not in ids and s2 in ids  # s2 保留


async def test_bulk_delete_ignores_other_users_sessions(auth_client, client):
    # 安全回归:user B 传 user A 的 session id,绝不删 A 的会话、也不计入 skipped
    aid = await _agent(auth_client)
    s_a = await _session(auth_client, aid)  # A 的会话
    other_token, _ = await register_user(client)
    r = await client.post(
        "/sessions/bulk-delete",
        json={"session_ids": [s_a]},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert r.json() == {"deleted": 0, "skipped": []}  # B 不拥有 → 静默忽略
    ids = {g["id"] for g in (await auth_client.get("/sessions")).json()}
    assert s_a in ids  # A 的会话原封不动


async def test_bulk_delete_ignores_nonexistent_and_empty(auth_client):
    # 不存在的 id 静默忽略;空列表 → 0/0
    r = await auth_client.post("/sessions/bulk-delete", json={"session_ids": [str(uuid.uuid4())]})
    assert r.json() == {"deleted": 0, "skipped": []}
    r2 = await auth_client.post("/sessions/bulk-delete", json={"session_ids": []})
    assert r2.json() == {"deleted": 0, "skipped": []}
