import pytest
from agent_cloud_backend.files.deps import get_file_store
from agent_cloud_backend.files.store import LocalFileStore
from agent_cloud_backend.main import create_app
from fastapi.testclient import TestClient

UID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(tmp_path):
    app = create_app()
    app.dependency_overrides[get_file_store] = lambda: LocalFileStore(str(tmp_path))
    return TestClient(app)


def test_list_empty_then_upload_then_list(client):
    assert client.get("/files", params={"user_id": UID}).json() == []
    r = client.post(
        "/files/upload",
        params={"user_id": UID, "path": ""},
        files=[("files", ("a.txt", b"hello", "text/plain"))],
    )
    assert r.status_code == 201
    assert r.json()[0]["name"] == "a.txt" and r.json()[0]["size"] == 5
    listing = client.get("/files", params={"user_id": UID}).json()
    assert [e["name"] for e in listing] == ["a.txt"]


def test_raw_download_and_preview(client):
    client.post("/files/upload", params={"user_id": UID},
                files=[("files", ("a.txt", b"hello", "text/plain"))])
    r = client.get("/files/raw", params={"user_id": UID, "path": "a.txt"})
    assert r.status_code == 200 and r.content == b"hello"
    assert "inline" in r.headers["content-disposition"]
    r2 = client.get("/files/raw", params={"user_id": UID, "path": "a.txt", "attachment": True})
    assert "attachment" in r2.headers["content-disposition"]


def test_raw_directory_returns_zip(client):
    client.post("/files/upload", params={"user_id": UID, "path": "d"},
                files=[("files", ("a.txt", b"x", "text/plain"))])
    r = client.get("/files/raw", params={"user_id": UID, "path": "d"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "d.zip" in r.headers["content-disposition"]


def test_mkdir_move_delete(client):
    assert client.post("/files/mkdir", json={"user_id": UID, "path": "d"}).status_code == 200
    client.post("/files/upload", params={"user_id": UID, "path": "d"},
                files=[("files", ("a.txt", b"x", "text/plain"))])
    assert client.post("/files/move",
                       json={"user_id": UID, "src": "d/a.txt", "dst": "d/b.txt"}).status_code == 200
    assert client.request("DELETE", "/files",
                          params={"user_id": UID, "path": "d"}).status_code == 204
    assert client.get("/files", params={"user_id": UID}).json() == []


def test_path_jail_rejected_400(client):
    assert client.get("/files", params={"user_id": UID, "path": "../.."}).status_code == 400


def test_not_found_404(client):
    assert client.get("/files/raw", params={"user_id": UID, "path": "nope.txt"}).status_code == 404


def test_mkdir_conflict_409(client):
    client.post("/files/mkdir", json={"user_id": UID, "path": "d"})
    assert client.post("/files/mkdir", json={"user_id": UID, "path": "d"}).status_code == 409


def test_upload_too_large_413(client, monkeypatch):
    # get_settings() 每次调用现读环境变量 → 设小上限触发 413
    monkeypatch.setenv("AGENT_CLOUD_FILE_UPLOAD_MAX_BYTES", "3")
    r = client.post("/files/upload", params={"user_id": UID},
                    files=[("files", ("big.bin", b"toolong", "application/octet-stream"))])
    assert r.status_code == 413
