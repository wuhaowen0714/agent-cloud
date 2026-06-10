import tempfile
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.config import get_settings
from agent_cloud_backend.files.deps import get_file_store
from agent_cloud_backend.files.errors import PathEscape
from agent_cloud_backend.files.store import FileStore
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.skill import SkillRepository
from agent_cloud_backend.schemas.skill import (
    SkillInstallFromWorkspaceRequest,
    SkillInstallRequest,
    SkillRead,
)
from agent_cloud_backend.skills.deps import get_object_store, get_skill_registry_root
from agent_cloud_backend.skills.manifest import SkillManifestError
from agent_cloud_backend.skills.service import ensure_builtin_skills, install_skill_from_dir
from agent_cloud_backend.skills.store import ObjectStore

router = APIRouter(prefix="/skills", tags=["skills"])


def _safe_extract_zip(fileobj, dest: Path) -> None:
    dest_resolved = dest.resolve()
    with zipfile.ZipFile(fileobj) as zf:
        for member in zf.namelist():
            target = (dest / member).resolve()
            if target != dest_resolved and dest_resolved not in target.parents:
                raise ValueError(f"unsafe path in archive: {member}")
        zf.extractall(dest)


def _locate_skill_root(extract_dir: Path) -> Path | None:
    if (extract_dir / "SKILL.md").is_file():
        return extract_dir
    # Ignore macOS archive cruft (__MACOSX/, .DS_Store) so a folder zipped on a
    # Mac — which contains a sibling __MACOSX/ — still resolves to its one skill dir.
    entries = [
        p for p in extract_dir.iterdir() if p.name != "__MACOSX" and not p.name.startswith(".")
    ]
    if len(entries) == 1 and entries[0].is_dir() and (entries[0] / "SKILL.md").is_file():
        return entries[0]
    return None


@router.get("", response_model=list[SkillRead])
async def list_skills(
    session: AsyncSession = Depends(get_session),
    store: ObjectStore = Depends(get_object_store),
    registry_root: Path = Depends(get_skill_registry_root),
    user: User = Depends(get_current_user),
):
    # GET 带幂等副作用(有意取舍):补装缺失的内置技能,存量用户任何一次
    # UI 加载即收敛(开箱即用),免做迁移;无缺失时零写入。
    repo = SkillRepository(session)
    if await ensure_builtin_skills(
        user_id=user.id, registry_root=registry_root, repo=repo, store=store
    ):
        await session.commit()
    return await repo.list_by_user(user.id)


@router.get("/registry", response_model=list[str])
def list_registry_skills(
    registry_root: Path = Depends(get_skill_registry_root),
    user: User = Depends(get_current_user),
):
    """列出 registry 里可安装的技能名(目录名 + 含 SKILL.md)。"""
    if not registry_root.exists():
        return []
    return sorted(
        p.name for p in registry_root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()
    )


@router.post("/install", response_model=SkillRead, status_code=status.HTTP_201_CREATED)
async def install_skill(
    body: SkillInstallRequest,
    session: AsyncSession = Depends(get_session),
    store: ObjectStore = Depends(get_object_store),
    registry_root: Path = Depends(get_skill_registry_root),
    user: User = Depends(get_current_user),
):
    if not body.name or "/" in body.name or "\\" in body.name or ".." in body.name:
        raise HTTPException(status_code=422, detail=f"invalid skill name: {body.name}")
    src_dir = registry_root / body.name
    if not (src_dir / "SKILL.md").is_file():
        raise HTTPException(status_code=404, detail=f"registry skill not found: {body.name}")
    try:
        skill = await install_skill_from_dir(
            user_id=user.id,
            src_dir=src_dir,
            source="registry",
            repo=SkillRepository(session),
            store=store,
        )
    except SkillManifestError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    await session.commit()
    return skill


@router.post(
    "/install-from-workspace", response_model=SkillRead, status_code=status.HTTP_201_CREATED
)
async def install_skill_from_workspace(
    body: SkillInstallFromWorkspaceRequest,
    session: AsyncSession = Depends(get_session),
    store: ObjectStore = Depends(get_object_store),
    file_store: FileStore = Depends(get_file_store),
    user: User = Depends(get_current_user),
):
    """把用户工作区里(agent 现写的)一个含 SKILL.md 的目录安装进技能池。

    复用 install_skill_from_dir;src_dir 经 file_store 围栏解析,确保就是文件抽屉里那个目录。
    """
    try:
        src_dir = file_store.abspath(str(user.id), body.path)
    except PathEscape as e:
        raise HTTPException(status_code=400, detail="invalid path") from e
    if not src_dir.is_dir():
        raise HTTPException(status_code=404, detail="workspace path is not a directory")
    # 安全:拒绝包内符号链接,否则后续 copytree 会把链接指向的宿主文件内容拷进技能包→物化进沙箱
    # (同 FileStore.zip_dir 的防护)。rglob 不会下探进符号链接目录,故顶层链接会先被这里发现、在
    # copytree 下探前就拒掉;put_dir/get_dir 另用 symlinks=True 作 TOCTOU 兜底(双保险)。
    if src_dir.is_symlink() or any(p.is_symlink() for p in src_dir.rglob("*")):
        raise HTTPException(status_code=400, detail="skill folder must not contain symlinks")
    try:
        skill = await install_skill_from_dir(
            user_id=user.id,
            src_dir=src_dir,
            source="workspace",
            repo=SkillRepository(session),
            store=store,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="directory has no SKILL.md") from e
    except SkillManifestError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    await session.commit()
    return skill


@router.post("/upload", response_model=SkillRead, status_code=status.HTTP_201_CREATED)
async def upload_skill(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    store: ObjectStore = Depends(get_object_store),
    user: User = Depends(get_current_user),
):
    if not get_settings().allow_uploaded_archives:
        raise HTTPException(status_code=403, detail="uploaded skill archives are disabled")
    with tempfile.TemporaryDirectory() as tmp:
        extract_dir = Path(tmp) / "pkg"
        extract_dir.mkdir()
        try:
            _safe_extract_zip(file.file, extract_dir)
        except (zipfile.BadZipFile, ValueError) as e:
            raise HTTPException(status_code=422, detail=f"invalid archive: {e}") from e
        root = _locate_skill_root(extract_dir)
        if root is None:
            raise HTTPException(status_code=422, detail="archive missing SKILL.md")
        try:
            skill = await install_skill_from_dir(
                user_id=user.id,
                src_dir=root,
                source="uploaded",
                repo=SkillRepository(session),
                store=store,
            )
        except SkillManifestError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
    await session.commit()
    return skill


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def uninstall_skill(
    skill_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    store: ObjectStore = Depends(get_object_store),
    user: User = Depends(get_current_user),
):
    repo = SkillRepository(session)
    skill = await repo.get(skill_id)
    if skill is None or skill.user_id != user.id:
        raise HTTPException(status_code=404, detail="skill not found")
    prefix = skill.package_ref
    await repo.delete(skill)
    await session.commit()
    store.delete_prefix(prefix)
