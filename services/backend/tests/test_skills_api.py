import io
import zipfile


async def _user(client, email):
    return (await client.post("/users", json={"email": email})).json()["id"]


def _zip_bytes(name="zippy", description="from zip"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            f"{name}/SKILL.md",
            f'---\nname: {name}\ndescription: "{description}"\n---\nbody\n',
        )
        zf.writestr(f"{name}/scripts/go.sh", "echo hi")
    buf.seek(0)
    return buf.getvalue()


async def test_install_from_registry_then_list(client):
    uid = await _user(client, "i1@e.com")
    r = await client.post("/skills/install", json={"user_id": uid, "name": "example-greeting"})
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "registry"
    r = await client.get(f"/skills?user_id={uid}")
    assert r.status_code == 200 and [s["name"] for s in r.json()] == ["example-greeting"]


async def test_install_unknown_registry_skill_404(client):
    uid = await _user(client, "i2@e.com")
    r = await client.post("/skills/install", json={"user_id": uid, "name": "does-not-exist"})
    assert r.status_code == 404


async def test_install_duplicate_409(client):
    uid = await _user(client, "i3@e.com")
    body = {"user_id": uid, "name": "example-greeting"}
    assert (await client.post("/skills/install", json=body)).status_code == 201
    assert (await client.post("/skills/install", json=body)).status_code == 409


async def test_upload_disabled_by_default_403(client):
    uid = await _user(client, "u1@e.com")
    r = await client.post(
        "/skills/upload",
        data={"user_id": uid},
        files={"file": ("s.zip", _zip_bytes(), "application/zip")},
    )
    assert r.status_code == 403


async def test_upload_enabled_201(client, monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_ALLOW_UPLOADED_ARCHIVES", "true")
    uid = await _user(client, "u2@e.com")
    r = await client.post(
        "/skills/upload",
        data={"user_id": uid},
        files={"file": ("s.zip", _zip_bytes(), "application/zip")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "uploaded" and r.json()["name"] == "zippy"


async def test_upload_zip_slip_rejected(client, monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_ALLOW_UPLOADED_ARCHIVES", "true")
    uid = await _user(client, "u3@e.com")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.sh", "echo pwned")
    buf.seek(0)
    r = await client.post(
        "/skills/upload",
        data={"user_id": uid},
        files={"file": ("s.zip", buf.getvalue(), "application/zip")},
    )
    assert r.status_code == 422


async def test_delete_skill(client):
    uid = await _user(client, "d1@e.com")
    sid = (
        await client.post("/skills/install", json={"user_id": uid, "name": "example-greeting"})
    ).json()["id"]
    assert (await client.delete(f"/skills/{sid}")).status_code == 204
    assert (await client.get(f"/skills?user_id={uid}")).json() == []
    assert (await client.delete(f"/skills/{sid}")).status_code == 404


async def test_install_rejects_traversal_name(client):
    uid = await _user(client, "trav@e.com")
    r = await client.post("/skills/install", json={"user_id": uid, "name": "../config"})
    assert r.status_code == 422


def _macos_zip_bytes(name="mac-skill"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{name}/SKILL.md", f'---\nname: {name}\ndescription: "d"\n---\nbody\n')
        # what macOS "Compress" adds alongside the real folder
        zf.writestr("__MACOSX/._SKILL.md", "cruft")
        zf.writestr(".DS_Store", "cruft")
    buf.seek(0)
    return buf.getvalue()


async def test_upload_macos_zip_with_dunder_macosx(client, monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_ALLOW_UPLOADED_ARCHIVES", "true")
    uid = await _user(client, "mac@e.com")
    r = await client.post(
        "/skills/upload",
        data={"user_id": uid},
        files={"file": ("s.zip", _macos_zip_bytes(), "application/zip")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "mac-skill"
