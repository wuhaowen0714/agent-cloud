from __future__ import annotations

import uuid
from pathlib import Path

from agent_cloud_backend.models.skill import Skill
from agent_cloud_backend.repositories.skill import AgentSkillEnableRepository, SkillRepository
from agent_cloud_backend.skills.manifest import SkillManifestError, parse_skill_md
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
    try:
        text = skill_md.read_text()
    except UnicodeDecodeError as exc:
        # 二进制/非 UTF-8 的 SKILL.md(agent 可能写出)→ 归为 manifest 错(422),而非 409/500。
        raise SkillManifestError("SKILL.md is not valid UTF-8") from exc
    manifest = parse_skill_md(text)

    if await repo.get_by_user_and_name(user_id, manifest.name) is not None:
        raise ValueError(f"skill already installed: {manifest.name}")

    prefix = skill_package_ref(user_id, manifest.name)
    skill = Skill(
        user_id=user_id,
        name=manifest.name,
        description=manifest.description,
        source=source,
        version=manifest.version,
        requires=manifest.requires,
        package_ref=prefix,
    )
    # Flush the row first: the unique (user_id, name) constraint is enforced
    # before any storage write, so a duplicate fails here having touched no
    # storage, and a concurrent same-name install can't delete the winner's
    # package dir. A later commit failure rolls the row back (orphan files,
    # which are unreachable, beat orphan rows).
    await repo.create(skill)
    store.put_dir(prefix, src_dir)
    return skill


async def ensure_builtin_skills(
    *,
    user_id: uuid.UUID,
    registry_root: Path,
    repo: SkillRepository,
    store: ObjectStore,
) -> list[Skill]:
    """把 registry 里该用户缺失的内置技能补装(幂等)。返回本次新装的。

    GET /skills 与注册时调用:无缺失时只有一次目录扫描 + 名字比对,零写入。
    目录名预筛、manifest.name 终判;并发 ensure 撞 ValueError(已装)视为达成。
    """
    if not registry_root.exists():
        return []
    installed = {s.name for s in await repo.list_by_user(user_id)}
    out: list[Skill] = []
    for p in sorted(registry_root.iterdir()):
        if not p.is_dir() or not (p / "SKILL.md").is_file() or p.name in installed:
            continue
        try:
            out.append(
                await install_skill_from_dir(
                    user_id=user_id, src_dir=p, source="registry", repo=repo, store=store
                )
            )
        except ValueError:
            pass
    return out


async def enable_builtin_skills(
    *,
    agent_config_id: uuid.UUID,
    user_id: uuid.UUID,
    repo: SkillRepository,
    enable_repo: AgentSkillEnableRepository,
) -> None:
    """把用户已装的全部内置(registry 来源)技能启用到该 agent。

    注册种子 main 与新建 agent 时调用——内置技能开箱即用;存量 agent 不回填
    (用户在 TopBar/设置里自行开关)。"""
    ids = [s.id for s in await repo.list_by_user(user_id) if s.source == "registry"]
    if ids:
        await enable_repo.replace_enabled_set(agent_config_id, ids)
