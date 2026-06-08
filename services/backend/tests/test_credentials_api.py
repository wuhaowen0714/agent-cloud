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
