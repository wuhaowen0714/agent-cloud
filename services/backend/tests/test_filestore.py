import io

import pytest
from agent_cloud_backend.files.errors import FileConflict, FileTooLarge, PathEscape
from agent_cloud_backend.files.store import LocalFileStore

UID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def store(tmp_path):
    return LocalFileStore(str(tmp_path))


def test_reads_do_not_create_workspace(store, tmp_path):
    # 读操作(list)不为任意 user_id 物化目录 → 防随机 UUID 灌目录 DoS(I3)
    assert store.list_dir(UID, "") == []
    assert not (tmp_path / UID / "workspace").exists()


def test_write_creates_workspace(store, tmp_path):
    store.write(UID, "a.txt", io.BytesIO(b"x"), 100)
    assert (tmp_path / UID / "workspace" / "a.txt").exists()


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


def test_list_dir_empty_for_fresh_user(store):
    assert store.list_dir(UID, "") == []


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


def test_zip_skips_symlinks(store, tmp_path):
    import zipfile

    store.write(UID, "proj/a.txt", io.BytesIO(b"aaa"), 100)
    (tmp_path / "outside.txt").write_text("secret")
    (tmp_path / UID / "workspace" / "proj" / "link.txt").symlink_to(tmp_path / "outside.txt")
    data = b"".join(store.zip_dir(UID, "proj"))
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.namelist() == ["a.txt"]  # symlink 不打包(防越狱读,M3)


class _BoomReader:
    """读到第二个 chunk 时抛错,模拟上传中途断流/IO 错误。"""

    def __init__(self) -> None:
        self.n = 0

    def read(self, _size: int) -> bytes:
        self.n += 1
        if self.n == 1:
            return b"partial"
        raise OSError("boom")


def test_write_cleans_partial_on_stream_error(store, tmp_path):
    with pytest.raises(OSError, match="boom"):
        store.write(UID, "x.txt", _BoomReader(), max_bytes=1_000_000)
    ws = tmp_path / UID / "workspace"
    assert not (ws / "x.txt").exists()  # 原子替换:真实文件未被污染(I2)
    assert list(ws.glob("*.part")) == []  # 临时文件已清
