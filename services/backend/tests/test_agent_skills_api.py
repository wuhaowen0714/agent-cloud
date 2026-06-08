import io
import uuid
import zipfile


async def _register(client):
    """注册新用户,返回其 access token(不改默认 header,便于多用户测试)。"""
    r = await client.post(
        "/auth/register", json={"email": f"{uuid.uuid4()}@e.com", "password": "password123"}
    )
    return r.json()["access_token"]


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


async def _agent(client, token, name="a"):
    return (
        await client.post(
            "/agent-configs",
            json={"name": name, "model": "m", "provider": "p"},
            headers=_hdr(token),
        )
    ).json()["id"]


async def _install(client, token, name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{name}/SKILL.md", f'---\nname: {name}\ndescription: "d"\n---\nx\n')
    buf.seek(0)
    return (
        await client.post(
            "/skills/upload",
            files={"file": ("s.zip", buf.getvalue(), "application/zip")},
            headers=_hdr(token),
        )
    ).json()["id"]


async def test_put_and_get_agent_skills(client, monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_ALLOW_UPLOADED_ARCHIVES", "true")
    tok = await _register(client)
    aid = await _agent(client, tok)
    s1 = await _install(client, tok, "alpha")
    s2 = await _install(client, tok, "beta")

    r = await client.put(
        f"/agent-configs/{aid}/skills", json={"skill_ids": [s1, s2]}, headers=_hdr(tok)
    )
    assert r.status_code == 200, r.text
    assert {s["name"] for s in r.json()} == {"alpha", "beta"}

    # 替换:只留 alpha
    r = await client.put(
        f"/agent-configs/{aid}/skills", json={"skill_ids": [s1]}, headers=_hdr(tok)
    )
    assert {s["name"] for s in r.json()} == {"alpha"}
    r = await client.get(f"/agent-configs/{aid}/skills", headers=_hdr(tok))
    assert {s["name"] for s in r.json()} == {"alpha"}


async def test_put_unknown_agent_404(client):
    tok = await _register(client)
    r = await client.put(
        f"/agent-configs/{uuid.uuid4()}/skills",
        json={"skill_ids": []},
        headers=_hdr(tok),
    )
    assert r.status_code == 404


async def test_put_rejects_other_users_skill(client, monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_ALLOW_UPLOADED_ARCHIVES", "true")
    owner = await _register(client)
    other = await _register(client)
    aid = await _agent(client, owner)
    foreign = await _install(client, other, "foreign")
    r = await client.put(
        f"/agent-configs/{aid}/skills", json={"skill_ids": [foreign]}, headers=_hdr(owner)
    )
    assert r.status_code == 400
