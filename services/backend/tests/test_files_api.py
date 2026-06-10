from types import SimpleNamespace

import pytest
from agent_cloud_backend.api.deps import get_current_user
from agent_cloud_backend.files.deps import get_file_store
from agent_cloud_backend.files.store import LocalFileStore
from agent_cloud_backend.main import create_app
from fastapi.testclient import TestClient

UID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(tmp_path):
    app = create_app()
    app.dependency_overrides[get_file_store] = lambda: LocalFileStore(str(tmp_path))
    # 文件端点只依赖 get_current_user(取 user.id)——桩成固定 UID,保持本测试 DB-free。
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=UID)
    return TestClient(app)


def test_list_empty_then_upload_then_list(client):
    assert client.get("/files").json() == []
    r = client.post(
        "/files/upload",
        params={"path": ""},
        files=[("files", ("a.txt", b"hello", "text/plain"))],
    )
    assert r.status_code == 201
    assert r.json()[0]["name"] == "a.txt" and r.json()[0]["size"] == 5
    listing = client.get("/files").json()
    assert [e["name"] for e in listing] == ["a.txt"]


def test_raw_download_and_preview(client):
    client.post("/files/upload", files=[("files", ("a.txt", b"hello", "text/plain"))])
    r = client.get("/files/raw", params={"path": "a.txt"})
    assert r.status_code == 200 and r.content == b"hello"
    assert "inline" in r.headers["content-disposition"]
    r2 = client.get("/files/raw", params={"path": "a.txt", "attachment": True})
    assert "attachment" in r2.headers["content-disposition"]


def test_raw_directory_returns_zip(client):
    client.post(
        "/files/upload", params={"path": "d"}, files=[("files", ("a.txt", b"x", "text/plain"))]
    )
    r = client.get("/files/raw", params={"path": "d"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "d.zip" in r.headers["content-disposition"]


def test_mkdir_move_delete(client):
    assert client.post("/files/mkdir", json={"path": "d"}).status_code == 200
    client.post(
        "/files/upload", params={"path": "d"}, files=[("files", ("a.txt", b"x", "text/plain"))]
    )
    assert client.post("/files/move", json={"src": "d/a.txt", "dst": "d/b.txt"}).status_code == 200
    assert client.request("DELETE", "/files", params={"path": "d"}).status_code == 204
    assert client.get("/files").json() == []


def test_path_jail_rejected_400(client):
    assert client.get("/files", params={"path": "../.."}).status_code == 400


def test_not_found_404(client):
    assert client.get("/files/raw", params={"path": "nope.txt"}).status_code == 404


def test_mkdir_conflict_409(client):
    client.post("/files/mkdir", json={"path": "d"})
    assert client.post("/files/mkdir", json={"path": "d"}).status_code == 409


def test_upload_too_large_413(client, monkeypatch):
    # get_settings() 每次调用现读环境变量 → 设小上限触发 413
    monkeypatch.setenv("AGENT_CLOUD_FILE_UPLOAD_MAX_BYTES", "3")
    r = client.post(
        "/files/upload", files=[("files", ("big.bin", b"toolong", "application/octet-stream"))]
    )
    assert r.status_code == 413


def test_move_into_a_file_is_400_not_500(client):
    # 把文件当目录用(move 进 f/inner)→ FileExistsError 应映射成 400,而非 500(I1)
    client.post("/files/upload", files=[("files", ("f", b"x", "text/plain"))])
    r = client.post("/files/move", json={"src": "f", "dst": "f/inner"})
    assert r.status_code == 400


def test_upload_into_a_file_is_400_not_500(client):
    client.post("/files/upload", files=[("files", ("f", b"x", "text/plain"))])
    r = client.post(
        "/files/upload", params={"path": "f"}, files=[("files", ("g", b"x", "text/plain"))]
    )
    assert r.status_code == 400


def test_content_disposition_filename_sanitized(client, tmp_path):
    # 直接落一个名字含 " 的文件,验证下载头不被破坏(M1)
    ws = tmp_path / UID / "workspace"
    ws.mkdir(parents=True)
    (ws / 'a"b.txt').write_text("x")
    r = client.get("/files/raw", params={"path": 'a"b.txt'})
    assert r.status_code == 200
    assert r.headers["content-disposition"].count('"') == 2


# ---- 非 ASCII 文件名:Content-Disposition 必须走 RFC 6266 filename*(用户报障:
# 「小说_最后一盏灯.txt」预览/下载双挂——HTTP 头仅 latin-1,塞原始 UTF-8 直接 500)----


def test_raw_supports_non_ascii_filenames(client):
    name = "小说_最后一盏灯.txt"
    r = client.post("/files/upload", files=[("files", (name, b"once upon", "text/plain"))])
    assert r.status_code == 201

    r = client.get("/files/raw", params={"path": name})
    assert r.status_code == 200
    assert r.content == b"once upon"
    cd = r.headers["content-disposition"]
    assert cd.startswith("inline")
    assert "filename*=UTF-8''" in cd  # RFC 6266 编码名(现代浏览器优先取它)

    r = client.get("/files/raw", params={"path": name, "attachment": "true"})
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment")


def test_raw_zip_dir_with_non_ascii_name(client):
    client.post("/files/mkdir", json={"path": "中文目录"})
    client.post(
        "/files/upload",
        params={"path": "中文目录"},
        files=[("files", ("a.txt", b"x", "text/plain"))],
    )
    r = client.get("/files/raw", params={"path": "中文目录"})
    assert r.status_code == 200
    assert "filename*=UTF-8''" in r.headers["content-disposition"]


# ---- 文件夹上传:multipart filename 携带相对路径(spec 2026-06-10-folder-upload)----


def test_upload_folder_with_relative_paths(client):
    r = client.post(
        "/files/upload",
        files=[
            ("files", ("proj/sub/a.txt", b"a", "text/plain")),
            ("files", ("proj/b.txt", b"b", "text/plain")),
        ],
    )
    assert r.status_code == 201
    assert {e["path"] for e in r.json()} == {"proj/sub/a.txt", "proj/b.txt"}
    assert [e["name"] for e in client.get("/files", params={"path": "proj/sub"}).json()] == [
        "a.txt"
    ]


def test_upload_folder_under_subdir_query(client):
    client.post("/files/mkdir", json={"path": "dest"})
    r = client.post(
        "/files/upload",
        params={"path": "dest"},
        files=[("files", ("pkg/x.txt", b"x", "text/plain"))],
    )
    assert r.status_code == 201
    assert r.json()[0]["path"] == "dest/pkg/x.txt"


def test_upload_rejects_traversal_in_filename(client):
    r = client.post("/files/upload", files=[("files", ("../evil.txt", b"x", "text/plain"))])
    assert r.status_code == 400


def test_upload_normalizes_backslashes(client):
    r = client.post("/files/upload", files=[("files", ("win\\style.txt", b"x", "text/plain"))])
    assert r.status_code == 201
    assert r.json()[0]["path"] == "win/style.txt"


def test_upload_plain_basename_unchanged(client):
    r = client.post("/files/upload", files=[("files", ("plain.txt", b"p", "text/plain"))])
    assert r.status_code == 201
    assert r.json()[0]["path"] == "plain.txt"


def test_upload_rejects_overlong_path_segment(client):
    # ENAMETOOLONG 等 OSError → 400(围栏内的非法路径形态,不该 500)
    r = client.post(
        "/files/upload", files=[("files", ("a" * 300 + "/x.txt", b"x", "text/plain"))]
    )
    assert r.status_code == 400


def test_sanitize_rel_upload_path_edge_cases():
    import pytest
    from agent_cloud_backend.api.files import _sanitize_rel_upload_path
    from agent_cloud_backend.files.errors import PathEscape

    with pytest.raises(PathEscape):
        _sanitize_rel_upload_path("a\0b.txt")  # null 字节
    with pytest.raises(PathEscape):
        _sanitize_rel_upload_path("a/../b.txt")  # 夹在中间的父引用
    # 绝对路径被锚定为围栏内相对路径(首空段丢弃)
    assert _sanitize_rel_upload_path("/etc/passwd") == "etc/passwd"
