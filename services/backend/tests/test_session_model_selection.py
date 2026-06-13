"""session 级模型选择 + BYOK 多模型 的端点测试。"""

import uuid


async def _auth(client):
    r = await client.post(
        "/auth/register", json={"email": f"{uuid.uuid4()}@e.com", "password": "password123"}
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _main_agent(client, h):
    return (await client.get("/agent-configs", headers=h)).json()[0]["id"]


async def test_platform_models_endpoint(client):
    h = await _auth(client)
    r = await client.get("/platform/models", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert "DeepSeek-V4-Pro" in body["models"]
    assert body["default"] == "DeepSeek-V4-Pro"


async def test_credential_models_round_trip(client):
    h = await _auth(client)
    r = await client.post(
        "/credentials",
        json={
            "name": "openrouter",
            "base_url": "https://or/v1",
            "api_key": "sk-x12345678",
            "models": ["gpt-4o", "claude-3.5"],
        },
        headers=h,
    )
    assert r.status_code == 201
    assert r.json()["models"] == ["gpt-4o", "claude-3.5"]
    got = (await client.get("/credentials", headers=h)).json()
    assert got[0]["models"] == ["gpt-4o", "claude-3.5"]


async def test_session_create_with_model(client):
    h = await _auth(client)
    aid = await _main_agent(client, h)
    body = (
        await client.post(
            "/sessions", json={"agent_config_id": aid, "model": "custom-x"}, headers=h
        )
    ).json()
    assert body["model"] == "custom-x" and body["credential_id"] is None


async def test_session_patch_model_and_credential(client):
    h = await _auth(client)
    aid = await _main_agent(client, h)
    cid = (
        await client.post(
            "/credentials",
            json={"name": "or", "base_url": "", "api_key": "sk-abcd1234", "models": ["m1"]},
            headers=h,
        )
    ).json()["id"]
    sid = (
        await client.post("/sessions", json={"agent_config_id": aid}, headers=h)
    ).json()["id"]
    # 切到 BYOK provider 的某模型
    r = await client.patch(
        f"/sessions/{sid}", json={"model": "m1", "credential_id": cid}, headers=h
    )
    assert r.status_code == 200
    assert r.json()["model"] == "m1" and r.json()["credential_id"] == cid
    # 显式传 null → 切回平台 sophnet
    r2 = await client.patch(f"/sessions/{sid}", json={"credential_id": None}, headers=h)
    assert r2.status_code == 200 and r2.json()["credential_id"] is None
