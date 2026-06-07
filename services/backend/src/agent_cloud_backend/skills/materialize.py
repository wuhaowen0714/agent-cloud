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


def _clear(path: Path) -> None:
    """删除 path,不论它是目录、文件还是符号链接。

    `.skills/` 落在 agent 可写的 work_subdir 内,agent 自己的 write_file/bash 可能把
    它替换成一个**文件或符号链接**;直接 `rmtree` 会在那种情况下抛 NotADirectoryError,
    把后续每个回合都钉死成 500(user 消息已先落库)。因此这里对三种类型都做处理。
    """
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


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

    v1 取舍与不变量(对照 spec §12.4/§11):
    - `.skills/` 落在 agent **可写**的 work_subdir 内(非 spec 设想的独立只读层);每回合
      清空+重铺,故 agent 自篡改只影响本会话且下回合即复位(清空对文件/符号链接也安全)。
    - 假定 backend 与 sandbox **共享同一 base_root 路径**(进程内/开发为真;生产需把用户卷挂到
      两侧相同路径)。
    - 依赖会话锁串行化同会话回合;若回合超过锁租约(无心跳),同会话的并发回合可能在仍有
      reader 时 rmtree 本目录——属既有租约设计的局限,留待心跳/租约细化。
    """
    skills_root = Path(base_root) / str(user_id) / work_subdir / SKILLS_SUBDIR
    _clear(skills_root)
    for skill in skills:
        store.get_dir(skill.package_ref, skills_root / skill.name)
