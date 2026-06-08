import uuid


async def _reg(client):
    r = await client.post(
        "/auth/register", json={"email": f"{uuid.uuid4()}@e.com", "password": "password123"}
    )
    body = r.json()
    return body["access_token"], body["user"]["id"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


async def test_protected_endpoints_require_auth(client):
    assert (await client.get("/agent-configs")).status_code == 401
    assert (await client.get("/sessions")).status_code == 401
    assert (await client.get("/skills")).status_code == 401
    assert (await client.get("/auth/me")).status_code == 401
    assert (await client.get("/files")).status_code == 401
    assert (await client.get("/memory?scope=user")).status_code == 401


async def test_bad_token_is_401(client):
    me = await client.get("/auth/me", headers={"Authorization": "Bearer x.y.z"})
    assert me.status_code == 401
    s = await client.get("/sessions", headers={"Authorization": "garbage"})
    assert s.status_code == 401


async def test_cross_user_session_is_404_and_not_listed(client):
    ta, _ = await _reg(client)
    tb, _ = await _reg(client)
    aid = (
        await client.post(
            "/agent-configs",
            json={"name": "a", "model": "m", "provider": "p"},
            headers=_h(ta),
        )
    ).json()["id"]
    sid = (await client.post("/sessions", json={"agent_config_id": aid}, headers=_h(ta))).json()[
        "id"
    ]
    # B 访问 A 的 session 资源 → 404(不泄漏存在)
    assert (await client.get(f"/sessions/{sid}/messages", headers=_h(tb))).status_code == 404
    assert (await client.post(f"/sessions/{sid}/turn/cancel", headers=_h(tb))).status_code == 404
    # B 的会话列表里看不到 A 的
    b_sessions = (await client.get("/sessions", headers=_h(tb))).json()
    assert sid not in [s["id"] for s in b_sessions]


async def test_cross_user_agent_patch_is_404(client):
    ta, _ = await _reg(client)
    tb, _ = await _reg(client)
    aid = (
        await client.post(
            "/agent-configs",
            json={"name": "a", "model": "m", "provider": "p"},
            headers=_h(ta),
        )
    ).json()["id"]
    assert (
        await client.patch(f"/agent-configs/{aid}", json={"name": "x"}, headers=_h(tb))
    ).status_code == 404


async def test_cross_user_create_session_on_foreign_agent_is_404(client):
    ta, _ = await _reg(client)
    tb, _ = await _reg(client)
    aid = (
        await client.post(
            "/agent-configs",
            json={"name": "a", "model": "m", "provider": "p"},
            headers=_h(ta),
        )
    ).json()["id"]
    assert (
        await client.post("/sessions", json={"agent_config_id": aid}, headers=_h(tb))
    ).status_code == 404


async def test_agent_configs_isolated_per_user(client):
    ta, _ = await _reg(client)
    tb, _ = await _reg(client)
    await client.post(
        "/agent-configs", json={"name": "a", "model": "m", "provider": "p"}, headers=_h(ta)
    )
    # B 列表为空(看不到 A 的 agent)
    assert (await client.get("/agent-configs", headers=_h(tb))).json() == []
