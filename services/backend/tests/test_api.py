import uuid


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
    r = await client.post(
        "/memory", json={"scope": "user", "owner_id": uid, "content": "likes tea"}
    )
    assert r.status_code == 201
    r = await client.get(f"/memory?scope=user&owner_id={uid}")
    assert r.status_code == 200 and r.json()[0]["content"] == "likes tea"


async def test_context_document_put_update_branch(client):
    """C1: PUT update branch must not 500. Insert then update same key, expect
    200 with refreshed content + updated_at present/advanced."""
    uid = (await client.post("/users", json={"email": "upd@example.com"})).json()["id"]
    key = {"scope": "user", "type": "USER", "owner_id": uid}

    r = await client.put("/context-documents", json={**key, "content": "v1"})
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["content"] == "v1"
    assert first["updated_at"] is not None

    # Update the SAME (scope, type, owner_id) -> exercises the UPDATE branch.
    r = await client.put("/context-documents", json={**key, "content": "v2"})
    assert r.status_code == 200, r.text
    second = r.json()
    assert second["id"] == first["id"]
    assert second["content"] == "v2"
    assert second["updated_at"] is not None
    assert second["updated_at"] >= first["updated_at"]


async def test_duplicate_email_returns_409(client):
    """I2: a unique-constraint violation should be 409, not 500, and must not
    leak raw SQL. A subsequent request on the same app must still work."""
    r = await client.post("/users", json={"email": "dup@example.com"})
    assert r.status_code == 201, r.text

    r = await client.post("/users", json={"email": "dup@example.com"})
    assert r.status_code == 409, r.text
    body = r.json()
    assert "detail" in body
    # Generic message only -- no leaked DB internals.
    assert "duplicate key" not in body["detail"].lower()
    assert "uq_" not in body["detail"]

    # The session/connection must be usable again after rollback.
    r = await client.post("/users", json={"email": "other@example.com"})
    assert r.status_code == 201, r.text


async def test_session_with_bogus_agent_config_returns_409(client):
    """I2: FK violation (non-existent agent_config_id) should be 409."""
    uid = (await client.post("/users", json={"email": "fk@example.com"})).json()["id"]
    bogus_agent = str(uuid.uuid4())
    r = await client.post("/sessions", json={"user_id": uid, "agent_config_id": bogus_agent})
    assert r.status_code == 409, r.text
    assert "detail" in r.json()


async def test_message_to_bogus_session_returns_409(client):
    """I2: FK violation (non-existent session_id) should be 409."""
    bogus_session = str(uuid.uuid4())
    r = await client.post(
        f"/sessions/{bogus_session}/messages",
        json={"role": "user", "content": {"text": "hi"}},
    )
    assert r.status_code == 409, r.text
    assert "detail" in r.json()


async def test_user_not_found_returns_404(client):
    """I1: GET an unknown user id -> 404."""
    r = await client.get(f"/users/{uuid.uuid4()}")
    assert r.status_code == 404, r.text


async def test_agent_config_patch_not_found_returns_404(client):
    """I1: PATCH an unknown agent-config id -> 404."""
    r = await client.patch(f"/agent-configs/{uuid.uuid4()}", json={"name": "nope"})
    assert r.status_code == 404, r.text


async def test_agent_config_patch_jsonb_fields(client):
    """I1: PATCH JSONB columns (enabled_tools, permissions) persists and bumps
    updated_at -- also guards the existing agent-config session.refresh."""
    uid = (await client.post("/users", json={"email": "json@example.com"})).json()["id"]
    created = (
        await client.post(
            "/agent-configs",
            json={"user_id": uid, "name": "c", "model": "m", "provider": "p"},
        )
    ).json()
    aid = created["id"]

    r = await client.patch(
        f"/agent-configs/{aid}",
        json={
            "enabled_tools": ["bash", "read"],
            "permissions": {"net": True, "fs": "ro"},
        },
    )
    assert r.status_code == 200, r.text
    patched = r.json()
    assert patched["enabled_tools"] == ["bash", "read"]
    assert patched["permissions"] == {"net": True, "fs": "ro"}
    assert patched["updated_at"] >= created["updated_at"]

    # Confirm persistence via a fresh read.
    listed = (await client.get(f"/agent-configs?user_id={uid}")).json()
    assert listed[0]["enabled_tools"] == ["bash", "read"]
    assert listed[0]["permissions"] == {"net": True, "fs": "ro"}


async def test_message_seq_ordering_three_rows(client):
    """I1: appending 3+ messages yields seq 0,1,2 and list returns them in
    order."""
    uid = (await client.post("/users", json={"email": "seq@example.com"})).json()["id"]
    aid = (
        await client.post(
            "/agent-configs",
            json={"user_id": uid, "name": "c", "model": "m", "provider": "p"},
        )
    ).json()["id"]
    sid = (await client.post("/sessions", json={"user_id": uid, "agent_config_id": aid})).json()[
        "id"
    ]

    for i in range(3):
        r = await client.post(
            f"/sessions/{sid}/messages",
            json={"role": "user", "content": {"text": f"m{i}"}},
        )
        assert r.status_code == 201, r.text
        assert r.json()["seq"] == i

    listed = (await client.get(f"/sessions/{sid}/messages")).json()
    assert [m["seq"] for m in listed] == [0, 1, 2]
    assert [m["content"]["text"] for m in listed] == ["m0", "m1", "m2"]
