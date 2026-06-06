import uuid

import pytest
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.skill import SkillRepository
from agent_cloud_backend.skills.service import install_skill_from_dir, skill_package_ref
from agent_cloud_backend.skills.store import LocalObjectStore


def _write_pkg(root, name="alpha", description="d"):
    pkg = root / name
    (pkg / "scripts").mkdir(parents=True)
    (pkg / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "{description}"\nrequires:\n  bins: [bash]\n---\nbody\n'
    )
    (pkg / "scripts" / "go.sh").write_text("echo hi")
    return pkg


async def _user(session):
    u = User(email=f"{uuid.uuid4()}@e.com")
    session.add(u)
    await session.flush()
    return u.id


async def test_install_registers_and_stores(session, tmp_path):
    uid = await _user(session)
    pkg = _write_pkg(tmp_path)
    store = LocalObjectStore(tmp_path / "store")
    skill = await install_skill_from_dir(
        user_id=uid, src_dir=pkg, source="registry",
        repo=SkillRepository(session), store=store,
    )
    assert skill.name == "alpha"
    assert skill.source == "registry"
    assert skill.package_ref == skill_package_ref(uid, "alpha")
    assert store.exists(skill.package_ref)


async def test_install_duplicate_rejected(session, tmp_path):
    uid = await _user(session)
    pkg = _write_pkg(tmp_path)
    store = LocalObjectStore(tmp_path / "store")
    repo = SkillRepository(session)
    await install_skill_from_dir(
        user_id=uid, src_dir=pkg, source="registry", repo=repo, store=store
    )
    with pytest.raises(ValueError):
        await install_skill_from_dir(
            user_id=uid, src_dir=pkg, source="registry", repo=repo, store=store
        )


async def test_install_missing_skill_md(session, tmp_path):
    uid = await _user(session)
    empty = tmp_path / "empty"
    empty.mkdir()
    store = LocalObjectStore(tmp_path / "store")
    with pytest.raises(FileNotFoundError):
        await install_skill_from_dir(
            user_id=uid, src_dir=empty, source="registry",
            repo=SkillRepository(session), store=store,
        )
