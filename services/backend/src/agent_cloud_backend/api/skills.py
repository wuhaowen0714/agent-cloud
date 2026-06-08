import tempfile
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.config import get_settings
from agent_cloud_backend.repositories.skill import SkillRepository
from agent_cloud_backend.schemas.skill import SkillInstallRequest, SkillRead
from agent_cloud_backend.skills.deps import get_object_store, get_skill_registry_root
from agent_cloud_backend.skills.manifest import SkillManifestError
from agent_cloud_backend.skills.service import install_skill_from_dir
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
async def list_skills(user_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await SkillRepository(session).list_by_user(user_id)


@router.get("/registry", response_model=list[str])
def list_registry_skills(registry_root: Path = Depends(get_skill_registry_root)):
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
):
    if not body.name or "/" in body.name or "\\" in body.name or ".." in body.name:
        raise HTTPException(status_code=422, detail=f"invalid skill name: {body.name}")
    src_dir = registry_root / body.name
    if not (src_dir / "SKILL.md").is_file():
        raise HTTPException(status_code=404, detail=f"registry skill not found: {body.name}")
    try:
        skill = await install_skill_from_dir(
            user_id=body.user_id,
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


@router.post("/upload", response_model=SkillRead, status_code=status.HTTP_201_CREATED)
async def upload_skill(
    user_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    store: ObjectStore = Depends(get_object_store),
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
                user_id=user_id,
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
):
    repo = SkillRepository(session)
    skill = await repo.get(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="skill not found")
    prefix = skill.package_ref
    await repo.delete(skill)
    await session.commit()
    store.delete_prefix(prefix)
