# Plan 9a: File Management — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A path-jailed `FileStore` abstraction + REST `/files` API that lets the frontend browse/preview/upload/download/delete/rename/mkdir in a user's persistent workspace, operating host-direct on `<host_root>/<user_id>/workspace`.

**Architecture:** `FileStore` Protocol with a v1 `LocalFileStore` (operates directly on the host workspace dir; every path resolved through a `_resolve` jail). A thin FastAPI router maps store calls + exceptions to HTTP. No DB involved (pure filesystem). Spec: [2026-06-07-file-management-design.md](../specs/2026-06-07-file-management-design.md).

**Tech Stack:** Python 3.13, FastAPI, pathlib/shutil/zipfile/mimetypes, pytest. `user_id: uuid.UUID` like the skills API. Settings via `get_settings()`; feature deps in `files/deps.py` (mirrors `skills/deps.py`).

---

## File Structure

- Create: `services/backend/src/agent_cloud_backend/files/__init__.py` — package marker.
- Create: `services/backend/src/agent_cloud_backend/files/errors.py` — `PathEscape`, `FileConflict`, `FileTooLarge` (not-found / not-a-dir / is-a-dir reuse builtins).
- Create: `services/backend/src/agent_cloud_backend/files/store.py` — `FileEntry`, `FileStore` Protocol, `LocalFileStore` (jail + ops).
- Create: `services/backend/src/agent_cloud_backend/files/deps.py` — `get_file_store()`.
- Create: `services/backend/src/agent_cloud_backend/schemas/file.py` — `FileEntryRead`, `MkdirRequest`, `MoveRequest`.
- Create: `services/backend/src/agent_cloud_backend/api/files.py` — `/files` router.
- Modify: `services/backend/src/agent_cloud_backend/config.py` — add `file_upload_max_bytes`.
- Modify: `services/backend/src/agent_cloud_backend/main.py` — import + register `files` router.
- Test: `services/backend/tests/test_filestore.py` — jail + operations.
- Test: `services/backend/tests/test_files_api.py` — endpoints + error codes.

**Test execution note:** file tests use `tmp_path` only (no DB/testcontainers) — fast. Run a single file with `cd services/backend && uv run pytest tests/test_filestore.py -v`. Full-suite regression still needs `TESTCONTAINERS_RYUK_DISABLED=true` (see memory).

---

## Task 1: Config flag + error types

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/config.py`
- Create: `services/backend/src/agent_cloud_backend/files/__init__.py`
- Create: `services/backend/src/agent_cloud_backend/files/errors.py`

- [ ] **Step 1: Add the upload-size config field**

In `config.py`, add to the `Settings` class near the other sandbox/limit fields:

```python
    # 文件管理:单文件上传上限(字节)。超出 → 413。
    file_upload_max_bytes: int = 100 * 1024 * 1024
```

- [ ] **Step 2: Create the files package + error types**

`files/__init__.py`: empty file.

`files/errors.py`:

```python
from __future__ import annotations


class FileError(Exception):
    """文件操作错误基类。"""


class PathEscape(FileError):
    """路径越出工作区围栏(.. / 绝对 / symlink 越狱 / null 字节)。"""


class FileConflict(FileError):
    """目标已存在(mkdir / move 目的地)。"""


class FileTooLarge(FileError):
    """上传超过 file_upload_max_bytes。"""
```

(Not-found / not-a-directory / is-a-directory reuse Python builtins `FileNotFoundError` / `NotADirectoryError` / `IsADirectoryError`, which pathlib/os raise naturally.)

- [ ] **Step 3: Commit**

```bash
git add services/backend/src/agent_cloud_backend/config.py services/backend/src/agent_cloud_backend/files/
git commit -m "feat(backend): file-management config flag + error types"
```

---

## Task 2: FileStore protocol + path jail (`_resolve`)

**Files:**
- Create: `services/backend/src/agent_cloud_backend/files/store.py`
- Test: `services/backend/tests/test_filestore.py`

- [ ] **Step 1: Write the failing jail tests (security-critical, test-first)**

`tests/test_filestore.py`:

```python
import io

import pytest
from agent_cloud_backend.files.errors import FileConflict, FileTooLarge, PathEscape
from agent_cloud_backend.files.store import LocalFileStore

UID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def store(tmp_path):
    return LocalFileStore(str(tmp_path))


def test_user_root_is_lazily_created(store, tmp_path):
    # 新用户没跑过沙箱:列根目录也应得到空列表,而非报错
    assert store.list_dir(UID, "") == []
    assert (tmp_path / UID / "workspace").is_dir()


@pytest.mark.parametrize("bad", ["..", "../x", "a/../../b", "/etc/passwd", "a\0b"])
def test_resolve_rejects_escapes(store, bad):
    with pytest.raises(PathEscape):
        store._resolve(UID, bad)


def test_resolve_rejects_symlink_escape(store, tmp_path):
    root = tmp_path / UID / "workspace"
    root.mkdir(parents=True)
    (tmp_path / "secret.txt").write_text("top secret")
    (root / "link").symlink_to(tmp_path / "secret.txt")  # 指向围栏外
    with pytest.raises(PathEscape):
        store._resolve(UID, "link")


def test_resolve_allows_in_jail_paths(store, tmp_path):
    p = store._resolve(UID, "sub/dir/file.txt")
    assert str(p).startswith(str((tmp_path / UID / "workspace").resolve()))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/backend && uv run pytest tests/test_filestore.py -v`
Expected: FAIL — `ModuleNotFoundError: agent_cloud_backend.files.store` / `LocalFileStore` not defined.

- [ ] **Step 3: Implement `FileEntry`, `FileStore`, and the jail**

`files/store.py`:

```python
from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Iterator, Protocol

from .errors import FileConflict, FileTooLarge, PathEscape


@dataclass
class FileEntry:
    name: str         # 基名,如 "app.py"
    path: str         # 相对工作区根的 posix 路径,无前导 "/";根目录为 ""
    is_dir: bool
    size: int         # 字节;目录为 0
    mtime: float      # epoch 秒


class FileStore(Protocol):
    def list_dir(self, user_id: str, rel_path: str) -> list[FileEntry]: ...
    def stat(self, user_id: str, rel_path: str) -> FileEntry: ...
    def open_read(self, user_id: str, rel_path: str) -> BinaryIO: ...
    def write(self, user_id: str, rel_path: str, data: BinaryIO, max_bytes: int) -> FileEntry: ...
    def mkdir(self, user_id: str, rel_path: str) -> FileEntry: ...
    def move(self, user_id: str, src: str, dst: str) -> FileEntry: ...
    def delete(self, user_id: str, rel_path: str) -> None: ...
    def zip_dir(self, user_id: str, rel_path: str) -> Iterator[bytes]: ...


_CHUNK = 1024 * 1024


class LocalFileStore:
    """直接在宿主文件系统上操作某用户的工作区(<host_root>/<user_id>/workspace)。"""

    def __init__(self, host_root: str) -> None:
        self._host_root = Path(host_root)

    def _user_root(self, user_id: str) -> Path:
        root = self._host_root / user_id / "workspace"
        root.mkdir(parents=True, exist_ok=True)  # 懒创建:新用户也能浏览/上传
        return root

    def _resolve(self, user_id: str, rel_path: str) -> Path:
        """把相对路径解析成围栏内的绝对路径;越界一律抛 PathEscape。"""
        if "\0" in rel_path:
            raise PathEscape("null byte in path")
        parts = [p for p in rel_path.strip("/").split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise PathEscape(f"parent traversal not allowed: {rel_path!r}")
        root = self._user_root(user_id).resolve()
        candidate = (root / Path(*parts)).resolve() if parts else root
        # resolve() 跟随 symlink:指向围栏外的链接解析后落在 root 外 → 拒绝
        if candidate != root and root not in candidate.parents:
            raise PathEscape(f"path escapes workspace: {rel_path!r}")
        return candidate
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/backend && uv run pytest tests/test_filestore.py -v`
Expected: PASS (5 jail/lazy-root tests).

- [ ] **Step 5: Commit**

```bash
git add services/backend/src/agent_cloud_backend/files/store.py services/backend/tests/test_filestore.py
git commit -m "feat(backend): FileStore + LocalFileStore path jail (test-first)"
```

---

## Task 3: LocalFileStore operations

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/files/store.py`
- Test: `services/backend/tests/test_filestore.py`

- [ ] **Step 1: Write the failing operation tests**

Append to `tests/test_filestore.py`:

```python
def test_write_then_list_stat_read(store):
    store.write(UID, "notes/a.txt", io.BytesIO(b"hello"), max_bytes=1000)
    entries = store.list_dir(UID, "")
    assert [(e.name, e.is_dir) for e in entries] == [("notes", True)]  # 目录优先
    sub = store.list_dir(UID, "notes")
    assert [(e.name, e.is_dir, e.size) for e in sub] == [("a.txt", False, 5)]
    assert store.stat(UID, "notes/a.txt").size == 5
    with store.open_read(UID, "notes/a.txt") as f:
        assert f.read() == b"hello"


def test_list_dir_sorts_dirs_first_then_name(store):
    store.write(UID, "b.txt", io.BytesIO(b"x"), 100)
    store.write(UID, "A.txt", io.BytesIO(b"x"), 100)
    store.mkdir(UID, "zdir")
    assert [e.name for e in store.list_dir(UID, "")] == ["zdir", "A.txt", "b.txt"]


def test_write_over_max_bytes_aborts_and_cleans_up(store, tmp_path):
    with pytest.raises(FileTooLarge):
        store.write(UID, "big.bin", io.BytesIO(b"x" * 50), max_bytes=10)
    assert not (tmp_path / UID / "workspace" / "big.bin").exists()  # 半截已删


def test_mkdir_conflict(store):
    store.mkdir(UID, "d")
    with pytest.raises(FileConflict):
        store.mkdir(UID, "d")


def test_move_renames(store):
    store.write(UID, "old.txt", io.BytesIO(b"x"), 100)
    e = store.move(UID, "old.txt", "new.txt")
    assert e.path == "new.txt"
    assert not store._resolve(UID, "old.txt").exists()


def test_move_conflict(store):
    store.write(UID, "a.txt", io.BytesIO(b"x"), 100)
    store.write(UID, "b.txt", io.BytesIO(b"x"), 100)
    with pytest.raises(FileConflict):
        store.move(UID, "a.txt", "b.txt")


def test_delete_file_and_dir_recursive(store):
    store.write(UID, "d/x.txt", io.BytesIO(b"x"), 100)
    store.delete(UID, "d")  # 递归删目录
    assert store.list_dir(UID, "") == []
    with pytest.raises(FileNotFoundError):
        store.stat(UID, "d")


def test_delete_root_refused(store):
    with pytest.raises(PathEscape):
        store.delete(UID, "")


def test_zip_dir_contains_files(store):
    import zipfile
    store.write(UID, "proj/a.txt", io.BytesIO(b"aaa"), 100)
    store.write(UID, "proj/sub/b.txt", io.BytesIO(b"bbb"), 100)
    data = b"".join(store.zip_dir(UID, "proj"))
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert sorted(zf.namelist()) == ["a.txt", "sub/b.txt"]


def test_missing_paths_raise_not_found(store):
    with pytest.raises(FileNotFoundError):
        store.stat(UID, "nope.txt")
    with pytest.raises(FileNotFoundError):
        store.open_read(UID, "nope.txt")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/backend && uv run pytest tests/test_filestore.py -v`
Expected: FAIL — `LocalFileStore` has no `list_dir`/`write`/etc.

- [ ] **Step 3: Implement the operations**

Append to `LocalFileStore` in `files/store.py`:

```python
    def _entry(self, root: Path, p: Path) -> FileEntry:
        st = p.stat()
        is_dir = p.is_dir()
        return FileEntry(
            name=p.name,
            path="" if p == root else p.relative_to(root).as_posix(),
            is_dir=is_dir,
            size=0 if is_dir else st.st_size,
            mtime=st.st_mtime,
        )

    def list_dir(self, user_id: str, rel_path: str) -> list[FileEntry]:
        root = self._user_root(user_id).resolve()
        target = self._resolve(user_id, rel_path)
        if not target.exists():
            raise FileNotFoundError(rel_path)
        if not target.is_dir():
            raise NotADirectoryError(rel_path)
        entries = [self._entry(root, c) for c in target.iterdir()]
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))  # 目录优先,名称升序
        return entries

    def stat(self, user_id: str, rel_path: str) -> FileEntry:
        root = self._user_root(user_id).resolve()
        target = self._resolve(user_id, rel_path)
        if not target.exists():
            raise FileNotFoundError(rel_path)
        return self._entry(root, target)

    def open_read(self, user_id: str, rel_path: str) -> BinaryIO:
        target = self._resolve(user_id, rel_path)
        if not target.exists():
            raise FileNotFoundError(rel_path)
        if target.is_dir():
            raise IsADirectoryError(rel_path)
        return target.open("rb")

    def write(self, user_id: str, rel_path: str, data: BinaryIO, max_bytes: int) -> FileEntry:
        root = self._user_root(user_id).resolve()
        target = self._resolve(user_id, rel_path)
        if target == root:
            raise PathEscape("cannot write to workspace root")
        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        try:
            with target.open("wb") as f:
                while True:
                    chunk = data.read(_CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise FileTooLarge(f"{rel_path}: exceeds {max_bytes} bytes")
                    f.write(chunk)
        except FileTooLarge:
            target.unlink(missing_ok=True)  # 删半截
            raise
        return self._entry(root, target)

    def mkdir(self, user_id: str, rel_path: str) -> FileEntry:
        root = self._user_root(user_id).resolve()
        target = self._resolve(user_id, rel_path)
        if target.exists():
            raise FileConflict(rel_path)
        target.mkdir(parents=True)
        return self._entry(root, target)

    def move(self, user_id: str, src: str, dst: str) -> FileEntry:
        root = self._user_root(user_id).resolve()
        s = self._resolve(user_id, src)
        d = self._resolve(user_id, dst)
        if not s.exists():
            raise FileNotFoundError(src)
        if d.exists():
            raise FileConflict(dst)
        if d == root:
            raise PathEscape("cannot overwrite workspace root")
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return self._entry(root, d)

    def delete(self, user_id: str, rel_path: str) -> None:
        root = self._user_root(user_id).resolve()
        target = self._resolve(user_id, rel_path)
        if target == root:
            raise PathEscape("cannot delete workspace root")
        if not target.exists():
            raise FileNotFoundError(rel_path)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    def zip_dir(self, user_id: str, rel_path: str) -> Iterator[bytes]:
        target = self._resolve(user_id, rel_path)
        if not target.exists():
            raise FileNotFoundError(rel_path)
        if not target.is_dir():
            raise NotADirectoryError(rel_path)
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(target.rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(target).as_posix())
        buf.seek(0)
        yield from iter(lambda: buf.read(_CHUNK), b"")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/backend && uv run pytest tests/test_filestore.py -v`
Expected: PASS (all jail + operation tests).

- [ ] **Step 5: Lint + commit**

```bash
cd services/backend && uv run ruff check src/agent_cloud_backend/files/ tests/test_filestore.py
git add services/backend/src/agent_cloud_backend/files/store.py services/backend/tests/test_filestore.py
git commit -m "feat(backend): LocalFileStore operations (list/read/write/mkdir/move/delete/zip)"
```

---

## Task 4: Schemas + deps + `/files` API + wiring

**Files:**
- Create: `services/backend/src/agent_cloud_backend/schemas/file.py`
- Create: `services/backend/src/agent_cloud_backend/files/deps.py`
- Create: `services/backend/src/agent_cloud_backend/api/files.py`
- Modify: `services/backend/src/agent_cloud_backend/main.py`
- Test: `services/backend/tests/test_files_api.py`

- [ ] **Step 1: Write the failing API tests**

`tests/test_files_api.py`:

```python
import io

import pytest
from agent_cloud_backend.config import get_settings
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
        "/files/upload", params={"user_id": UID, "path": ""},
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
    assert client.request("DELETE", "/files", params={"user_id": UID, "path": "d"}).status_code == 204
    assert client.get("/files", params={"user_id": UID}).json() == []


def test_path_jail_rejected_400(client):
    assert client.get("/files", params={"user_id": UID, "path": "../.."}).status_code == 400


def test_not_found_404(client):
    assert client.get("/files/raw", params={"user_id": UID, "path": "nope.txt"}).status_code == 404


def test_mkdir_conflict_409(client):
    client.post("/files/mkdir", json={"user_id": UID, "path": "d"})
    assert client.post("/files/mkdir", json={"user_id": UID, "path": "d"}).status_code == 409


def test_upload_too_large_413(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "file_upload_max_bytes", 3)
    r = client.post("/files/upload", params={"user_id": UID},
                    files=[("files", ("big.bin", b"toolong", "application/octet-stream"))])
    assert r.status_code == 413
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/backend && uv run pytest tests/test_files_api.py -v`
Expected: FAIL — `agent_cloud_backend.files.deps` / `/files` routes don't exist (404s).

- [ ] **Step 3: Create schemas**

`schemas/file.py`:

```python
from pydantic import BaseModel


class FileEntryRead(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int
    mtime: float


class MkdirRequest(BaseModel):
    user_id: str
    path: str


class MoveRequest(BaseModel):
    user_id: str
    src: str
    dst: str
```

- [ ] **Step 4: Create the file-store dependency**

`files/deps.py` (mirrors `skills/deps.py`):

```python
from agent_cloud_backend.config import get_settings

from .store import FileStore, LocalFileStore


def get_file_store() -> FileStore:
    return LocalFileStore(get_settings().effective_sandbox_host_root)
```

- [ ] **Step 5: Create the API router**

`api/files.py`:

```python
import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.files.deps import get_file_store
from agent_cloud_backend.files.errors import FileConflict, FileTooLarge, PathEscape
from agent_cloud_backend.files.store import FileStore
from agent_cloud_backend.schemas.file import FileEntryRead, MkdirRequest, MoveRequest

router = APIRouter(prefix="/files", tags=["files"])

_CHUNK = 1024 * 1024


def _http_from(exc: Exception) -> HTTPException:
    if isinstance(exc, PathEscape):
        return HTTPException(status.HTTP_400_BAD_REQUEST, "invalid path")
    if isinstance(exc, FileConflict):
        return HTTPException(status.HTTP_409_CONFLICT, "already exists")
    if isinstance(exc, FileTooLarge):
        return HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file too large")
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    if isinstance(exc, (NotADirectoryError, IsADirectoryError)):
        return HTTPException(status.HTTP_400_BAD_REQUEST, "wrong file type")
    raise exc  # 未知错误 → 冒泡成 500


@router.get("", response_model=list[FileEntryRead])
def list_files(
    user_id: uuid.UUID,
    path: str = "",
    store: FileStore = Depends(get_file_store),
):
    try:
        return store.list_dir(str(user_id), path)
    except Exception as exc:
        raise _http_from(exc) from exc


@router.get("/raw")
def raw(
    user_id: uuid.UUID,
    path: str,
    attachment: bool = False,
    store: FileStore = Depends(get_file_store),
):
    uid = str(user_id)
    try:
        entry = store.stat(uid, path)
    except Exception as exc:
        raise _http_from(exc) from exc
    if entry.is_dir:
        name = (entry.name or "workspace") + ".zip"
        return StreamingResponse(
            store.zip_dir(uid, path),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )
    fh = store.open_read(uid, path)
    media = mimetypes.guess_type(entry.name)[0] or "application/octet-stream"
    disp = "attachment" if attachment else "inline"

    def _stream():
        try:
            yield from iter(lambda: fh.read(_CHUNK), b"")
        finally:
            fh.close()

    return StreamingResponse(
        _stream(),
        media_type=media,
        headers={"Content-Disposition": f'{disp}; filename="{entry.name}"'},
    )


@router.post("/upload", response_model=list[FileEntryRead], status_code=status.HTTP_201_CREATED)
def upload(
    user_id: uuid.UUID,
    path: str = "",
    files: list[UploadFile] = File(...),
    store: FileStore = Depends(get_file_store),
    settings: Settings = Depends(get_settings),
):
    out = []
    for uf in files:
        name = Path(uf.filename or "upload").name  # 只取 basename,消毒
        dest = f"{path}/{name}" if path else name
        try:
            out.append(store.write(str(user_id), dest, uf.file, settings.file_upload_max_bytes))
        except Exception as exc:
            raise _http_from(exc) from exc
    return out


@router.post("/mkdir", response_model=FileEntryRead)
def mkdir(body: MkdirRequest, store: FileStore = Depends(get_file_store)):
    try:
        return store.mkdir(body.user_id, body.path)
    except Exception as exc:
        raise _http_from(exc) from exc


@router.post("/move", response_model=FileEntryRead)
def move(body: MoveRequest, store: FileStore = Depends(get_file_store)):
    try:
        return store.move(body.user_id, body.src, body.dst)
    except Exception as exc:
        raise _http_from(exc) from exc


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    user_id: uuid.UUID,
    path: str = Query(...),
    store: FileStore = Depends(get_file_store),
):
    try:
        store.delete(str(user_id), path)
    except Exception as exc:
        raise _http_from(exc) from exc
```

- [ ] **Step 6: Register the router in `main.py`**

Add `files` to the import block and the `include_router` loop:

```python
from agent_cloud_backend.api import (
    agent_configs,
    agent_skills,
    context_documents,
    files,
    memory_entries,
    messages,
    sessions,
    skills,
    turn,
    users,
)
```

```python
    for module in (
        users,
        agent_configs,
        sessions,
        messages,
        context_documents,
        memory_entries,
        turn,
        skills,
        agent_skills,
        files,
    ):
        app.include_router(module.router)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd services/backend && uv run pytest tests/test_files_api.py -v`
Expected: PASS (list/upload/raw/zip/mkdir/move/delete + jail 400 + 404 + 409 + 413).

- [ ] **Step 8: Lint + full backend regression + commit**

```bash
cd services/backend && uv run ruff check src/agent_cloud_backend/ tests/
TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q
git add services/backend/src/agent_cloud_backend/ services/backend/tests/test_files_api.py
git commit -m "feat(backend): /files REST API (list/raw/upload/mkdir/move/delete)"
```

Expected: ruff clean; full suite green.

---

## Self-Review

- **Spec coverage:** browse (`list_dir`/`GET /files`) ✓; preview/download (`open_read`/`GET /files/raw` inline+attachment, content-type via mimetypes) ✓; folder zip ✓; upload multifile + size cap 413 ✓; mkdir/move/delete ✓; path jail (test-first, .. / absolute / \0 / symlink) ✓; lazy root ✓; errors→codes (400/404/409/413) ✓.
- **Type consistency:** `FileEntry` fields == `FileEntryRead` fields; `FileStore` method names identical across protocol/impl/API; `write(..., max_bytes)` signature consistent store↔API.
- **No placeholders:** every step has full code + exact run command + expected result.
- **Out of scope (per spec):** object store, in-browser edit, auth — not in this plan.
