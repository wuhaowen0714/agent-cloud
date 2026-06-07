import uuid

from agent_cloud_backend.models.skill import Skill
from agent_cloud_backend.skills.materialize import (
    SKILLS_SUBDIR,
    materialize_enabled_skills,
    skill_location,
)
from agent_cloud_backend.skills.store import LocalObjectStore


def _store_with_skill(tmp_path, uid, name="example"):
    store = LocalObjectStore(tmp_path / "obj")
    src = tmp_path / f"src-{name}"
    (src / "scripts").mkdir(parents=True)
    (src / "SKILL.md").write_text(f"# {name}")
    (src / "scripts" / "go.sh").write_text("echo hi")
    ref = f"users/{uid}/skills/{name}"
    store.put_dir(ref, src)
    return store, ref


def _skill(uid, name, ref):
    return Skill(
        user_id=uid, name=name, description="d", source="registry",
        version="1.0.0", requires={}, package_ref=ref,
    )


def test_skill_location():
    assert skill_location("foo") == ".skills/foo/SKILL.md"


def test_materialize_copies_into_work_subdir(tmp_path):
    uid = uuid.uuid4()
    store, ref = _store_with_skill(tmp_path, uid, "example")
    materialize_enabled_skills(
        base_root=tmp_path / "boxes", user_id=uid, work_subdir="sessions/s1",
        skills=[_skill(uid, "example", ref)], store=store,
    )
    base = tmp_path / "boxes" / str(uid) / "sessions/s1" / SKILLS_SUBDIR / "example"
    assert (base / "SKILL.md").read_text() == "# example"
    assert (base / "scripts" / "go.sh").read_text() == "echo hi"


def test_materialize_removes_stale_skills(tmp_path):
    uid = uuid.uuid4()
    store, ref = _store_with_skill(tmp_path, uid, "keep")
    wd = "sessions/s1"
    stale = tmp_path / "boxes" / str(uid) / wd / SKILLS_SUBDIR / "stale"
    stale.mkdir(parents=True)
    (stale / "SKILL.md").write_text("old")
    materialize_enabled_skills(
        base_root=tmp_path / "boxes", user_id=uid, work_subdir=wd,
        skills=[_skill(uid, "keep", ref)], store=store,
    )
    root = tmp_path / "boxes" / str(uid) / wd / SKILLS_SUBDIR
    assert (root / "keep" / "SKILL.md").exists()
    assert not (root / "stale").exists()


def test_materialize_empty_clears_skills_dir(tmp_path):
    uid = uuid.uuid4()
    wd = "sessions/s1"
    root = tmp_path / "boxes" / str(uid) / wd / SKILLS_SUBDIR
    (root / "x").mkdir(parents=True)
    materialize_enabled_skills(
        base_root=tmp_path / "boxes", user_id=uid, work_subdir=wd, skills=[],
        store=LocalObjectStore(tmp_path / "obj"),
    )
    assert not root.exists()


def test_materialize_replaces_file_at_skills_path(tmp_path):
    # agent 可在 work_subdir 内用 write_file 把 .skills 写成一个文件;下回合物化必须
    # 能处理(否则 rmtree 抛 NotADirectoryError → 持久 500)。
    uid = uuid.uuid4()
    store, ref = _store_with_skill(tmp_path, uid, "keep")
    wd = "sessions/s1"
    skills_root = tmp_path / "boxes" / str(uid) / wd / SKILLS_SUBDIR
    skills_root.parent.mkdir(parents=True)
    skills_root.write_text("agent clobbered this")  # .skills 是个文件,不是目录
    materialize_enabled_skills(
        base_root=tmp_path / "boxes", user_id=uid, work_subdir=wd,
        skills=[_skill(uid, "keep", ref)], store=store,
    )
    assert skills_root.is_dir()
    assert (skills_root / "keep" / "SKILL.md").read_text() == "# keep"
