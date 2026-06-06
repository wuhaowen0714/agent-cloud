async def _user(client, email):
    return (await client.post("/users", json={"email": email})).json()["id"]


async def _agent(client, uid, name="a"):
    return (
        await client.post(
            "/agent-configs",
            json={"user_id": uid, "name": name, "model": "m", "provider": "p"},
        )
    ).json()["id"]


async def _install(client, uid, name):
    # 只有 example-greeting 在内置 registry;为多 skill 测试,上传 zip
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{name}/SKILL.md", f'---\nname: {name}\ndescription: "d"\n---\nx\n')
    buf.seek(0)
    return (
        await client.post(
            "/skills/upload",
            data={"user_id": uid},
            files={"file": ("s.zip", buf.getvalue(), "application/zip")},
        )
    ).json()["id"]


async def test_put_and_get_agent_skills(client, monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_ALLOW_UPLOADED_ARCHIVES", "true")
    uid = await _user(client, "as1@e.com")
    aid = await _agent(client, uid)
    s1 = await _install(client, uid, "alpha")
    s2 = await _install(client, uid, "beta")

    r = await client.put(f"/agent-configs/{aid}/skills", json={"skill_ids": [s1, s2]})
    assert r.status_code == 200, r.text
    assert {s["name"] for s in r.json()} == {"alpha", "beta"}

    # 替换:只留 alpha
    r = await client.put(f"/agent-configs/{aid}/skills", json={"skill_ids": [s1]})
    assert {s["name"] for s in r.json()} == {"alpha"}
    r = await client.get(f"/agent-configs/{aid}/skills")
    assert {s["name"] for s in r.json()} == {"alpha"}


async def test_put_unknown_agent_404(client):
    import uuid

    r = await client.put(f"/agent-configs/{uuid.uuid4()}/skills", json={"skill_ids": []})
    assert r.status_code == 404


async def test_put_rejects_other_users_skill(client, monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_ALLOW_UPLOADED_ARCHIVES", "true")
    owner = await _user(client, "owner@e.com")
    other = await _user(client, "other@e.com")
    aid = await _agent(client, owner)
    foreign = await _install(client, other, "foreign")
    r = await client.put(f"/agent-configs/{aid}/skills", json={"skill_ids": [foreign]})
    assert r.status_code == 400
