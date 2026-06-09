import uuid


async def test_agent_config_crud(auth_client):
    r = await auth_client.post(
        "/agent-configs",
        json={"name": "coder", "model": "claude-x", "provider": "anthropic"},
    )
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    r = await auth_client.patch(f"/agent-configs/{aid}", json={"name": "coder2"})
    assert r.status_code == 200 and r.json()["name"] == "coder2"
    r = await auth_client.get("/agent-configs")
    assert r.status_code == 200 and len(r.json()) == 1


async def test_session_and_messages(auth_client):
    aid = (
        await auth_client.post(
            "/agent-configs", json={"name": "c", "model": "m", "provider": "p"}
        )
    ).json()["id"]
    r = await auth_client.post("/sessions", json={"agent_config_id": aid})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["work_subdir"] == "workspace"

    r = await auth_client.post(
        f"/sessions/{sid}/messages", json={"role": "user", "content": {"text": "hello"}}
    )
    assert r.status_code == 201 and r.json()["seq"] == 0
    r = await auth_client.get(f"/sessions/{sid}/messages")
    assert r.status_code == 200 and len(r.json()) == 1


async def test_context_documents_and_memory(auth_client):
    r = await auth_client.put(
        "/context-documents", json={"scope": "user", "type": "USER", "content": "# me"}
    )
    assert r.status_code == 200, r.text
    r = await auth_client.put("/memory", json={"scope": "user", "content": "likes tea"})
    assert r.status_code == 200, r.text
    r = await auth_client.get("/memory?scope=user")
    assert r.status_code == 200 and r.json()["content"] == "likes tea"


async def test_context_document_put_update_branch(auth_client):
    """PUT update branch must not 500. Insert then update same key, expect 200."""
    key = {"scope": "user", "type": "USER"}
    r = await auth_client.put("/context-documents", json={**key, "content": "v1"})
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["content"] == "v1"
    assert first["updated_at"] is not None

    r = await auth_client.put("/context-documents", json={**key, "content": "v2"})
    assert r.status_code == 200, r.text
    second = r.json()
    assert second["id"] == first["id"]
    assert second["content"] == "v2"
    assert second["updated_at"] >= first["updated_at"]


async def test_duplicate_email_returns_409(client):
    """注册重复邮箱 → 409,不泄漏 SQL;之后仍可用。"""
    r = await client.post(
        "/auth/register", json={"email": "dup@example.com", "password": "password123"}
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/auth/register", json={"email": "dup@example.com", "password": "password123"}
    )
    assert r.status_code == 409, r.text
    body = r.json()
    assert "detail" in body
    assert "duplicate key" not in body["detail"].lower()
    assert "uq_" not in body["detail"]
    r = await client.post(
        "/auth/register", json={"email": "other@example.com", "password": "password123"}
    )
    assert r.status_code == 201, r.text


async def test_session_with_bogus_agent_config_returns_404(auth_client):
    """引用不属于本人/不存在的 agent_config → 404(owner 校验)。"""
    r = await auth_client.post("/sessions", json={"agent_config_id": str(uuid.uuid4())})
    assert r.status_code == 404, r.text


async def test_message_to_bogus_session_returns_404(auth_client):
    """向不属于本人/不存在的 session 发消息 → 404(owner 校验)。"""
    r = await auth_client.post(
        f"/sessions/{uuid.uuid4()}/messages",
        json={"role": "user", "content": {"text": "hi"}},
    )
    assert r.status_code == 404, r.text


async def test_agent_config_patch_not_found_returns_404(auth_client):
    r = await auth_client.patch(f"/agent-configs/{uuid.uuid4()}", json={"name": "nope"})
    assert r.status_code == 404, r.text


async def test_agent_config_patch_jsonb_fields(auth_client):
    created = (
        await auth_client.post(
            "/agent-configs", json={"name": "c", "model": "m", "provider": "p"}
        )
    ).json()
    aid = created["id"]
    r = await auth_client.patch(
        f"/agent-configs/{aid}",
        json={"enabled_tools": ["bash", "read"], "permissions": {"net": True, "fs": "ro"}},
    )
    assert r.status_code == 200, r.text
    patched = r.json()
    assert patched["enabled_tools"] == ["bash", "read"]
    assert patched["permissions"] == {"net": True, "fs": "ro"}
    assert patched["updated_at"] >= created["updated_at"]

    listed = (await auth_client.get("/agent-configs")).json()
    assert listed[0]["enabled_tools"] == ["bash", "read"]
    assert listed[0]["permissions"] == {"net": True, "fs": "ro"}


async def test_message_seq_ordering_three_rows(auth_client):
    aid = (
        await auth_client.post(
            "/agent-configs", json={"name": "c", "model": "m", "provider": "p"}
        )
    ).json()["id"]
    sid = (await auth_client.post("/sessions", json={"agent_config_id": aid})).json()["id"]

    for i in range(3):
        r = await auth_client.post(
            f"/sessions/{sid}/messages", json={"role": "user", "content": {"text": f"m{i}"}}
        )
        assert r.status_code == 201, r.text
        assert r.json()["seq"] == i

    listed = (await auth_client.get(f"/sessions/{sid}/messages")).json()
    assert [m["seq"] for m in listed] == [0, 1, 2]
    assert [m["content"]["text"] for m in listed] == ["m0", "m1", "m2"]
