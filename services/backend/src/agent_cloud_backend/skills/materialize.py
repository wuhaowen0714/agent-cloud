from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from agent_cloud_backend.models.skill import Skill
from agent_cloud_backend.skills.store import ObjectStore

SKILLS_SUBDIR = ".skills"


def skill_location(name: str) -> str:
    """回合内 agent 读取 SKILL.md 的路径(相对 work_subdir,落在沙箱工具容器内)。"""
    return f"{SKILLS_SUBDIR}/{name}/SKILL.md"


def materialize_enabled_skills(
    *,
    base_root: Path,
    user_id: uuid.UUID,
    work_subdir: str,
    skills: list[Skill],
    store: ObjectStore,
) -> None:
    """把已启用 skill 从对象存储铺到 <base_root>/<user_id>/<work_subdir>/.skills/<name>/。

    先整体清空 .skills/ 再逐个铺:这样停用/卸载的 skill 不会在本会话残留,
    每回合的 .skills/ 恰好等于当前启用集(天然失效,无需缓存)。同会话回合被会话
    锁串行化;不同会话(含同用户不同 agent)用不同 work_subdir,互不干扰。
    """
    skills_root = Path(base_root) / str(user_id) / work_subdir / SKILLS_SUBDIR
    if skills_root.exists():
        shutil.rmtree(skills_root)
    for skill in skills:
        store.get_dir(skill.package_ref, skills_root / skill.name)
