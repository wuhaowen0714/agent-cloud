from __future__ import annotations

import uuid
from pathlib import Path

from agent_cloud_backend.models.skill import Skill
from agent_cloud_backend.repositories.skill import SkillRepository
from agent_cloud_backend.skills.manifest import parse_skill_md
from agent_cloud_backend.skills.store import ObjectStore


def skill_package_ref(user_id: uuid.UUID, name: str) -> str:
    return f"users/{user_id}/skills/{name}"


async def install_skill_from_dir(
    *,
    user_id: uuid.UUID,
    src_dir: Path,
    source: str,
    repo: SkillRepository,
    store: ObjectStore,
) -> Skill:
    """解析 SKILL.md → 存对象存储 → 注册 DB。

    name 重复抛 ValueError;缺 SKILL.md 抛 FileNotFoundError。
    """
    skill_md = Path(src_dir) / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError("package missing SKILL.md")
    manifest = parse_skill_md(skill_md.read_text())

    if await repo.get_by_user_and_name(user_id, manifest.name) is not None:
        raise ValueError(f"skill already installed: {manifest.name}")

    prefix = skill_package_ref(user_id, manifest.name)
    store.put_dir(prefix, src_dir)
    try:
        skill = Skill(
            user_id=user_id,
            name=manifest.name,
            description=manifest.description,
            source=source,
            version=manifest.version,
            requires=manifest.requires,
            package_ref=prefix,
        )
        return await repo.create(skill)
    except Exception:
        # DB 注册失败(如并发唯一冲突)→ 回滚已写入的对象存储,避免孤儿包
        store.delete_prefix(prefix)
        raise
