import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker


async def _register(client):
    r = await client.post(
        "/auth/register", json={"email": f"{uuid.uuid4()}@e.com", "password": "password123"}
    )
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_register_seeds_default_agent_and_session(client):
    h = await _register(client)
    agents = (await client.get("/agent-configs", headers=h)).json()
    assert [a["name"] for a in agents] == ["main"]
    assert agents[0]["model"] == "DeepSeek-V4-Pro"
    assert agents[0]["provider"] == "openai"
    sessions = (await client.get("/sessions", headers=h)).json()
    assert len(sessions) == 1
    assert sessions[0]["agent_config_id"] == agents[0]["id"]


async def _first_session(client, h):
    return (await client.get("/sessions", headers=h)).json()[0]


async def test_rename_session(client):
    h = await _register(client)
    sid = (await _first_session(client, h))["id"]
    r = await client.patch(f"/sessions/{sid}", json={"title": "  我的会话  "}, headers=h)
    assert r.status_code == 200
    assert r.json()["title"] == "我的会话"  # trim
    # 校验:空/超长 → 422
    assert (
        await client.patch(f"/sessions/{sid}", json={"title": "   "}, headers=h)
    ).status_code == 422
    assert (
        await client.patch(f"/sessions/{sid}", json={"title": "x" * 201}, headers=h)
    ).status_code == 422
    # 他人 → 404
    h2 = await _register(client)
    assert (
        await client.patch(f"/sessions/{sid}", json={"title": "hack"}, headers=h2)
    ).status_code == 404


async def test_register_conflict_leaves_no_orphans(client, engine):
    email = f"{uuid.uuid4()}@e.com"
    await client.post("/auth/register", json={"email": email, "password": "password123"})
    r = await client.post("/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 409  # 重复注册
    from agent_cloud_backend.models.agent_config import AgentConfig

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        n = (await db.execute(select(func.count()).select_from(AgentConfig))).scalar_one()
    assert n == 1  # 只有第一次注册播种的那一个,409 没有残留
