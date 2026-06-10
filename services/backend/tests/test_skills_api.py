import io
import os
import uuid
import zipfile


async def _auth(client):
    reg = await client.post(
        "/auth/register", json={"email": f"{uuid.uuid4()}@e.com", "password": "password123"}
    )
    client.headers["Authorization"] = f"Bearer {reg.json()['access_token']}"


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
    await _auth(client)
    r = await client.post("/skills/install", json={"name": "skill-creator"})
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "registry"
    r = await client.get("/skills")
    assert r.status_code == 200 and [s["name"] for s in r.json()] == ["skill-creator"]


async def test_install_unknown_registry_skill_404(client):
    await _auth(client)
    r = await client.post("/skills/install", json={"name": "does-not-exist"})
    assert r.status_code == 404


async def test_install_duplicate_409(client):
    await _auth(client)
    body = {"name": "skill-creator"}
    assert (await client.post("/skills/install", json=body)).status_code == 201
    assert (await client.post("/skills/install", json=body)).status_code == 409


async def test_upload_disabled_by_default_403(client):
    await _auth(client)
    r = await client.post(
        "/skills/upload",
        files={"file": ("s.zip", _zip_bytes(), "application/zip")},
    )
    assert r.status_code == 403


async def test_upload_enabled_201(client, monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_ALLOW_UPLOADED_ARCHIVES", "true")
    await _auth(client)
    r = await client.post(
        "/skills/upload",
        files={"file": ("s.zip", _zip_bytes(), "application/zip")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "uploaded" and r.json()["name"] == "zippy"


async def test_upload_zip_slip_rejected(client, monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_ALLOW_UPLOADED_ARCHIVES", "true")
    await _auth(client)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.sh", "echo pwned")
    buf.seek(0)
    r = await client.post(
        "/skills/upload",
        files={"file": ("s.zip", buf.getvalue(), "application/zip")},
    )
    assert r.status_code == 422


async def test_delete_skill(client, monkeypatch):
    # 纯删除语义用非内置(uploaded)技能验证——内置删了会被 ensure 补回(另测)
    monkeypatch.setenv("AGENT_CLOUD_ALLOW_UPLOADED_ARCHIVES", "true")
    await _auth(client)
    sid = (
        await client.post(
            "/skills/upload", files={"file": ("s.zip", _zip_bytes(), "application/zip")}
        )
    ).json()["id"]
    assert (await client.delete(f"/skills/{sid}")).status_code == 204
    # zippy 已删不再出现;内置 skill-creator 被本次列表的 ensure 补装
    assert [s["name"] for s in (await client.get("/skills")).json()] == ["skill-creator"]
    assert (await client.delete(f"/skills/{sid}")).status_code == 404


async def test_install_rejects_traversal_name(client):
    await _auth(client)
    r = await client.post("/skills/install", json={"name": "../config"})
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
    await _auth(client)
    r = await client.post(
        "/skills/upload",
        files={"file": ("s.zip", _macos_zip_bytes(), "application/zip")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "mac-skill"


async def test_list_registry_skills(auth_client):
    r = await auth_client.get("/skills/registry")
    assert r.status_code == 200
    assert "skill-creator" in r.json()  # 仓库内置 registry 技能


_WS_SKILL_MD = (
    '---\nname: {name}\ndescription: "Does a thing. Use when needed."\nversion: "1.0.0"\n'
    "---\n# {name}\nbody\n"
)


async def _upload(client, path, filename, data: bytes):
    return await client.post(
        "/files/upload",
        params={"path": path},
        files=[("files", (filename, data, "text/markdown"))],
    )


async def test_install_from_workspace_then_list(client):
    await _auth(client)
    md = _WS_SKILL_MD.format(name="wsskill").encode()
    assert (await _upload(client, "wsskill", "SKILL.md", md)).status_code == 201
    r = await client.post("/skills/install-from-workspace", json={"path": "wsskill"})
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "wsskill" and r.json()["source"] == "workspace"
    assert "wsskill" in [s["name"] for s in (await client.get("/skills")).json()]


async def test_install_from_workspace_missing_skill_md_404(client):
    await _auth(client)
    await _upload(client, "notaskill", "foo.txt", b"hi")  # 目录里没有 SKILL.md
    r = await client.post("/skills/install-from-workspace", json={"path": "notaskill"})
    assert r.status_code == 404


async def test_install_from_workspace_nonexistent_path_404(client):
    await _auth(client)
    r = await client.post("/skills/install-from-workspace", json={"path": "nope"})
    assert r.status_code == 404


async def test_install_from_workspace_path_escape_400(client):
    await _auth(client)
    r = await client.post("/skills/install-from-workspace", json={"path": "../escape"})
    assert r.status_code == 400


async def test_install_from_workspace_duplicate_409(client):
    await _auth(client)
    md = _WS_SKILL_MD.format(name="dupskill").encode()
    await _upload(client, "dupskill", "SKILL.md", md)
    assert (
        await client.post("/skills/install-from-workspace", json={"path": "dupskill"})
    ).status_code == 201
    assert (
        await client.post("/skills/install-from-workspace", json={"path": "dupskill"})
    ).status_code == 409


async def test_install_from_workspace_binary_skill_md_422(client):
    # agent 写出二进制/非 UTF-8 的 SKILL.md → 归类为 manifest 错(422),而非 409/500。
    await _auth(client)
    await _upload(client, "binskill", "SKILL.md", b"\xff\xfe\x00not utf-8")
    r = await client.post("/skills/install-from-workspace", json={"path": "binskill"})
    assert r.status_code == 422


async def test_install_from_workspace_rejects_symlinks(client, tmp_path):
    # 安全:包内符号链接(agent 可用 bash `ln -s` 造)会被 copytree 跟随,拷进宿主文件内容 → 拒绝。
    reg = await client.post(
        "/auth/register", json={"email": f"{uuid.uuid4()}@e.com", "password": "password123"}
    )
    body = reg.json()
    client.headers["Authorization"] = f"Bearer {body['access_token']}"
    uid = body["user"]["id"]
    await _upload(client, "symskill", "SKILL.md", _WS_SKILL_MD.format(name="symskill").encode())
    ws = tmp_path / "filestore" / uid / "workspace" / "symskill"
    os.symlink("/etc/hosts", ws / "leak")  # 指向围栏外的宿主文件
    r = await client.post("/skills/install-from-workspace", json={"path": "symskill"})
    assert r.status_code == 400


# ---- 内置技能自动补装(GET /skills 幂等 ensure)----


async def test_list_skills_auto_installs_builtins(client):
    # 新用户首次 GET /skills:内置技能(skill-creator)被自动补装
    await _auth(client)
    r = await client.get("/skills")
    assert r.status_code == 200
    assert [s["name"] for s in r.json()] == ["skill-creator"]
    assert r.json()[0]["source"] == "registry"


async def test_list_skills_ensure_is_idempotent(client):
    await _auth(client)
    await client.get("/skills")
    r = await client.get("/skills")
    assert [s["name"] for s in r.json()] == ["skill-creator"]  # 不重复安装


async def test_install_after_auto_ensure_conflicts(client):
    await _auth(client)
    await client.get("/skills")
    r = await client.post("/skills/install", json={"name": "skill-creator"})
    assert r.status_code == 409  # 已被 ensure 装好


async def test_deleted_builtin_comes_back_on_next_list(client):
    # 内置技能没有"真删除":前端不暴露删除入口,后端就算删了,下次列表 ensure 即恢复(新 id)
    await _auth(client)
    sid = (await client.get("/skills")).json()[0]["id"]
    assert (await client.delete(f"/skills/{sid}")).status_code == 204
    relisted = (await client.get("/skills")).json()
    assert [s["name"] for s in relisted] == ["skill-creator"]
    assert relisted[0]["id"] != sid
