import uuid


async def test_memory_empty_default(auth_client):
    r = await auth_client.get("/memory?scope=user")
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == ""
    assert body["version"] == 0


async def test_memory_put_then_get_bumps_version(auth_client):
    r = await auth_client.put("/memory", json={"scope": "user", "content": "- likes tea"})
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "- likes tea"
    assert r.json()["version"] == 1

    r = await auth_client.get("/memory?scope=user")
    assert r.json()["content"] == "- likes tea"

    r = await auth_client.put("/memory", json={"scope": "user", "content": "- likes coffee"})
    assert r.json()["version"] == 2  # 第二次写 = 新版本
    assert r.json()["content"] == "- likes coffee"


async def test_memory_delete_clears(auth_client):
    await auth_client.put("/memory", json={"scope": "user", "content": "x"})
    r = await auth_client.delete("/memory?scope=user")
    assert r.status_code == 200, r.text
    assert r.json()["content"] == ""
    r = await auth_client.get("/memory?scope=user")
    assert r.json()["content"] == ""


async def test_memory_agent_scope_requires_agent_id(auth_client):
    r = await auth_client.put("/memory", json={"scope": "agent", "content": "x"})
    assert r.status_code == 422  # scope=agent 必须给 agent_id


async def test_memory_agent_scope_cross_tenant_404(auth_client):
    r = await auth_client.put(
        "/memory", json={"scope": "agent", "agent_id": str(uuid.uuid4()), "content": "x"}
    )
    assert r.status_code == 404  # 不属本人/不存在 → 404
