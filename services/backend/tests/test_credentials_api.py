import uuid


async def _auth_headers(client):
    r = await client.post(
        "/auth/register", json={"email": f"{uuid.uuid4()}@e.com", "password": "password123"}
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_create_returns_masked_never_plaintext(client):
    h = await _auth_headers(client)
    r = await client.post(
        "/credentials",
        json={"name": "openrouter", "base_url": "https://or/v1", "api_key": "sk-abcdef123456"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["masked"] == "sk-…3456"
    assert "api_key" not in body and "sk-abcdef123456" not in r.text


async def test_list_only_own_masked(client):
    h = await _auth_headers(client)
    await client.post(
        "/credentials", json={"name": "a", "base_url": "", "api_key": "sk-zzzz1111"}, headers=h
    )
    r = await client.get("/credentials", headers=h)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1 and rows[0]["masked"] == "sk-…1111"


async def test_requires_auth(client):
    assert (await client.get("/credentials")).status_code == 401


async def test_cross_user_delete_404(client):
    h1 = await _auth_headers(client)
    cid = (
        await client.post(
            "/credentials", json={"name": "a", "base_url": "", "api_key": "sk-aaaa2222"}, headers=h1
        )
    ).json()["id"]
    h2 = await _auth_headers(client)
    assert (await client.delete(f"/credentials/{cid}", headers=h2)).status_code == 404
    # 本人删成功
    assert (await client.delete(f"/credentials/{cid}", headers=h1)).status_code == 204


async def _mk_cred(client, headers, api_key="sk-abcd1234"):
    return (
        await client.post(
            "/credentials", json={"name": "c", "base_url": "", "api_key": api_key}, headers=headers
        )
    ).json()["id"]


async def test_agent_key_ref_must_be_owned(client):
    h = await _auth_headers(client)
    base = {"name": "a", "model": "m", "provider": "openai"}
    # 非法 uuid → 422
    r = await client.post("/agent-configs", json={**base, "key_ref": "not-a-uuid"}, headers=h)
    assert r.status_code == 422
    # 他人的 credential id → 404(不泄漏存在性)
    h2 = await _auth_headers(client)
    foreign = await _mk_cred(client, h2)
    r2 = await client.post("/agent-configs", json={**base, "key_ref": foreign}, headers=h)
    assert r2.status_code == 404
    # 本人的 credential → 201
    own = await _mk_cred(client, h)
    r3 = await client.post("/agent-configs", json={**base, "key_ref": own}, headers=h)
    assert r3.status_code == 201 and r3.json()["key_ref"] == own
    # PATCH 同样校验:他人的 → 404
    aid = r3.json()["id"]
    r4 = await client.patch(f"/agent-configs/{aid}", json={"key_ref": foreign}, headers=h)
    assert r4.status_code == 404


async def test_deleting_credential_nulls_agent_key_ref(client):
    h = await _auth_headers(client)
    cid = await _mk_cred(client, h)
    aid = (
        await client.post(
            "/agent-configs",
            json={"name": "a", "model": "m", "provider": "openai", "key_ref": cid},
            headers=h,
        )
    ).json()["id"]
    assert (await client.delete(f"/credentials/{cid}", headers=h)).status_code == 204
    agents = (await client.get("/agent-configs", headers=h)).json()
    agent = next(x for x in agents if x["id"] == aid)
    assert agent["key_ref"] is None  # 删除凭据后 agent 的 key_ref 被置空
