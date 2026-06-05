async def test_user_crud(client):
    r = await client.post("/users", json={"email": "x@example.com"})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = await client.get(f"/users/{uid}")
    assert r.status_code == 200 and r.json()["email"] == "x@example.com"


async def test_agent_config_crud(client):
    uid = (await client.post("/users", json={"email": "a@example.com"})).json()["id"]
    r = await client.post(
        "/agent-configs",
        json={"user_id": uid, "name": "coder", "model": "claude-x", "provider": "anthropic"},
    )
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    r = await client.patch(f"/agent-configs/{aid}", json={"name": "coder2"})
    assert r.status_code == 200 and r.json()["name"] == "coder2"
    r = await client.get(f"/agent-configs?user_id={uid}")
    assert r.status_code == 200 and len(r.json()) == 1


async def test_session_and_messages(client):
    uid = (await client.post("/users", json={"email": "s@example.com"})).json()["id"]
    aid = (
        await client.post(
            "/agent-configs",
            json={"user_id": uid, "name": "c", "model": "m", "provider": "p"},
        )
    ).json()["id"]
    r = await client.post("/sessions", json={"user_id": uid, "agent_config_id": aid})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["work_subdir"] == f"sessions/{sid}"

    r = await client.post(
        f"/sessions/{sid}/messages", json={"role": "user", "content": {"text": "hello"}}
    )
    assert r.status_code == 201 and r.json()["seq"] == 0
    r = await client.get(f"/sessions/{sid}/messages")
    assert r.status_code == 200 and len(r.json()) == 1


async def test_context_documents_and_memory(client):
    uid = (await client.post("/users", json={"email": "d@example.com"})).json()["id"]
    r = await client.put(
        "/context-documents",
        json={"scope": "user", "type": "USER", "owner_id": uid, "content": "# me"},
    )
    assert r.status_code == 200, r.text
    r = await client.post("/memory", json={"scope": "user", "owner_id": uid, "content": "likes tea"})
    assert r.status_code == 201
    r = await client.get(f"/memory?scope=user&owner_id={uid}")
    assert r.status_code == 200 and r.json()[0]["content"] == "likes tea"
