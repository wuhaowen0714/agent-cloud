import pytest
from agent_cloud_backend.skills.store import LocalObjectStore


def test_put_get_roundtrip(tmp_path):
    src = tmp_path / "src"
    (src / "scripts").mkdir(parents=True)
    (src / "SKILL.md").write_text("hi")
    (src / "scripts" / "go.sh").write_text("echo go")

    store = LocalObjectStore(tmp_path / "store")
    store.put_dir("users/u1/skills/demo", src)
    assert store.exists("users/u1/skills/demo")

    out = tmp_path / "out"
    store.get_dir("users/u1/skills/demo", out)
    assert (out / "SKILL.md").read_text() == "hi"
    assert (out / "scripts" / "go.sh").read_text() == "echo go"


def test_put_overwrites_existing(tmp_path):
    store = LocalObjectStore(tmp_path / "store")
    a = tmp_path / "a"
    a.mkdir()
    (a / "SKILL.md").write_text("v1")
    store.put_dir("p", a)
    b = tmp_path / "b"
    b.mkdir()
    (b / "SKILL.md").write_text("v2")
    store.put_dir("p", b)
    out = tmp_path / "out"
    store.get_dir("p", out)
    assert (out / "SKILL.md").read_text() == "v2"
    assert not (out / "stale").exists()


def test_delete_prefix(tmp_path):
    store = LocalObjectStore(tmp_path / "store")
    a = tmp_path / "a"
    a.mkdir()
    (a / "SKILL.md").write_text("x")
    store.put_dir("p", a)
    store.delete_prefix("p")
    assert not store.exists("p")
    store.delete_prefix("p")  # 幂等


def test_get_missing_raises(tmp_path):
    store = LocalObjectStore(tmp_path / "store")
    with pytest.raises(FileNotFoundError):
        store.get_dir("nope", tmp_path / "out")


def test_prefix_traversal_rejected(tmp_path):
    store = LocalObjectStore(tmp_path / "store")
    with pytest.raises(ValueError):
        store.exists("../escape")


def test_empty_prefix_rejected(tmp_path):
    store = LocalObjectStore(tmp_path / "store")
    with pytest.raises(ValueError):
        store.delete_prefix("")
    with pytest.raises(ValueError):
        store.exists(".")
