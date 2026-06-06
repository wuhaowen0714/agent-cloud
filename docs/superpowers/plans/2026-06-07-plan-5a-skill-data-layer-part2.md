# Plan 5a (续): Tasks 6–11

> 接 `2026-06-07-plan-5a-skill-data-layer.md`。同样遵守该文件顶部「测试约定」(backend 测试用 `TESTCONTAINERS_RYUK_DISABLED=true --timeout=120`,绝对路径 cd)。

---

## Task 6: repositories

**Files:**
- Create: `services/backend/src/agent_cloud_backend/repositories/skill.py`
- Test: `services/backend/tests/test_repo_skills.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_repo_skills.py`:

```python
import uuid

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.skill import Skill
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.skill import (
    AgentSkillEnableRepository,
    SkillRepository,
)


async def _user(session) -> uuid.UUID:
    u = User(email=f"{uuid.uuid4()}@e.com")
    session.add(u)
    await session.flush()
    return u.id


async def _agent(session, user_id) -> uuid.UUID:
    a = AgentConfig(user_id=user_id, name="a", model="m", provider="p")
    session.add(a)
    await session.flush()
    return a.id


def _skill(user_id, name) -> Skill:
    return Skill(
        user_id=user_id,
        name=name,
        description="d",
        source="registry",
        version="1.0.0",
        requires={},
        package_ref=f"users/{user_id}/skills/{name}",
    )


async def test_list_by_user_sorted(session):
    uid = await _user(session)
    repo = SkillRepository(session)
    await repo.create(_skill(uid, "beta"))
    await repo.create(_skill(uid, "alpha"))
    names = [s.name for s in await repo.list_by_user(uid)]
    assert names == ["alpha", "beta"]


async def test_get_by_user_and_name(session):
    uid = await _user(session)
    repo = SkillRepository(session)
    await repo.create(_skill(uid, "alpha"))
    assert (await repo.get_by_user_and_name(uid, "alpha")) is not None
    assert (await repo.get_by_user_and_name(uid, "nope")) is None


async def test_set_enabled_upsert(session):
    uid = await _user(session)
    aid = await _agent(session, uid)
    s = await SkillRepository(session).create(_skill(uid, "alpha"))
    repo = AgentSkillEnableRepository(session)
    row = await repo.set_enabled(aid, s.id, True)
    assert row.enabled is True
    row2 = await repo.set_enabled(aid, s.id, False)
    assert row2.enabled is False  # 同一行更新,不新增


async def test_replace_enabled_set(session):
    uid = await _user(session)
    aid = await _agent(session, uid)
    srepo = SkillRepository(session)
    s1 = await srepo.create(_skill(uid, "alpha"))
    s2 = await srepo.create(_skill(uid, "beta"))
    s3 = await srepo.create(_skill(uid, "gamma"))
    repo = AgentSkillEnableRepository(session)
    await repo.replace_enabled_set(aid, [s1.id, s2.id])
    assert {s.name for s in await repo.list_enabled_for_agent(aid)} == {"alpha", "beta"}
    # 替换:去掉 beta,加 gamma
    await repo.replace_enabled_set(aid, [s1.id, s3.id])
    assert {s.name for s in await repo.list_enabled_for_agent(aid)} == {"alpha", "gamma"}


async def test_list_enabled_excludes_disabled(session):
    uid = await _user(session)
    aid = await _agent(session, uid)
    s = await SkillRepository(session).create(_skill(uid, "alpha"))
    repo = AgentSkillEnableRepository(session)
    await repo.set_enabled(aid, s.id, False)
    assert await repo.list_enabled_for_agent(aid) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_repo_skills.py -q --timeout=120
```
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 写实现**

Create `repositories/skill.py`:

```python
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.models.skill import AgentSkillEnable, Skill
from agent_cloud_backend.repositories.base import BaseRepository


class SkillRepository(BaseRepository[Skill]):
    model = Skill

    async def list_by_user(self, user_id: uuid.UUID) -> list[Skill]:
        result = await self.session.execute(
            select(Skill).where(Skill.user_id == user_id).order_by(Skill.name)
        )
        return list(result.scalars().all())

    async def get_by_user_and_name(self, user_id: uuid.UUID, name: str) -> Skill | None:
        result = await self.session.execute(
            select(Skill).where(Skill.user_id == user_id, Skill.name == name)
        )
        return result.scalar_one_or_none()


class AgentSkillEnableRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_enabled(
        self, agent_config_id: uuid.UUID, skill_id: uuid.UUID, enabled: bool
    ) -> AgentSkillEnable:
        row = await self.session.get(AgentSkillEnable, (agent_config_id, skill_id))
        if row is None:
            row = AgentSkillEnable(
                agent_config_id=agent_config_id, skill_id=skill_id, enabled=enabled
            )
            self.session.add(row)
        else:
            row.enabled = enabled
        await self.session.flush()
        return row

    async def replace_enabled_set(
        self, agent_config_id: uuid.UUID, skill_ids: list[uuid.UUID]
    ) -> None:
        result = await self.session.execute(
            select(AgentSkillEnable).where(
                AgentSkillEnable.agent_config_id == agent_config_id
            )
        )
        existing = {r.skill_id: r for r in result.scalars().all()}
        wanted = set(skill_ids)
        for sid in wanted:
            row = existing.get(sid)
            if row is None:
                self.session.add(
                    AgentSkillEnable(
                        agent_config_id=agent_config_id, skill_id=sid, enabled=True
                    )
                )
            else:
                row.enabled = True
        for sid, row in existing.items():
            if sid not in wanted:
                row.enabled = False
        await self.session.flush()

    async def list_enabled_for_agent(self, agent_config_id: uuid.UUID) -> list[Skill]:
        result = await self.session.execute(
            select(Skill)
            .join(AgentSkillEnable, AgentSkillEnable.skill_id == Skill.id)
            .where(
                AgentSkillEnable.agent_config_id == agent_config_id,
                AgentSkillEnable.enabled.is_(True),
            )
            .order_by(Skill.name)
        )
        return list(result.scalars().all())
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q --timeout=120
```
Expected: 全绿。

- [ ] **Step 5: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/src/agent_cloud_backend/repositories/skill.py services/backend/tests/test_repo_skills.py && git commit -m "feat(backend): Skill + AgentSkillEnable repositories"
```

---

## Task 7: schemas + 内置 registry 示例 skill

**Files:**
- Create: `services/backend/src/agent_cloud_backend/schemas/skill.py`
- Create: `services/backend/src/agent_cloud_backend/skill_registry/example-greeting/SKILL.md`
- Create: `services/backend/src/agent_cloud_backend/skill_registry/example-greeting/scripts/greet.sh`
- Test: `services/backend/tests/test_skill_manifest.py`(追加一条:内置 registry 示例可解析)

- [ ] **Step 1: 写 schema**

Create `schemas/skill.py`:

```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str
    source: str
    version: str
    requires: dict
    package_ref: str
    created_at: datetime


class SkillInstallRequest(BaseModel):
    user_id: uuid.UUID
    name: str  # 内置 registry 中的 skill 名


class AgentSkillsUpdate(BaseModel):
    skill_ids: list[uuid.UUID]
```

- [ ] **Step 2: 写内置 registry 示例**

Create `skill_registry/example-greeting/SKILL.md`:

```markdown
---
name: example-greeting
description: "Print a friendly greeting. Bundled example skill for tests and demos."
requires:
  bins: [bash]
version: "1.0.0"
---

# example-greeting

Run `bash scripts/greet.sh <name>` to print a greeting.
```

Create `skill_registry/example-greeting/scripts/greet.sh`:

```bash
#!/usr/bin/env bash
echo "Hello, ${1:-world}!"
```

- [ ] **Step 3: 追加 registry 解析测试**

在 `tests/test_skill_manifest.py` 末尾追加:

```python
def test_bundled_registry_example_parses():
    from pathlib import Path

    import agent_cloud_backend

    root = Path(agent_cloud_backend.__file__).parent / "skill_registry" / "example-greeting"
    m = parse_skill_md((root / "SKILL.md").read_text())
    assert m.name == "example-greeting"
    assert m.requires == {"bins": ["bash"]}
    assert (root / "scripts" / "greet.sh").is_file()
```

- [ ] **Step 4: 确保示例随包打包**

确认 `pyproject.toml` 的 `[tool.hatch.build.targets.wheel] packages = ["src/agent_cloud_backend"]` 已覆盖该子目录(包内数据文件随源码树)。无需改动;此步仅核对。

- [ ] **Step 5: 跑测试确认通过**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_skill_manifest.py -q --timeout=120
```
Expected: 全 passed（含 bundled registry 解析）。

- [ ] **Step 6: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/src/agent_cloud_backend/schemas/skill.py services/backend/src/agent_cloud_backend/skill_registry services/backend/tests/test_skill_manifest.py && git commit -m "feat(backend): skill schemas + bundled registry example skill"
```

---

## Task 8: install service(install/upload 共用)

**Files:**
- Create: `services/backend/src/agent_cloud_backend/skills/service.py`
- Test: `services/backend/tests/test_skill_service.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_skill_service.py`:

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_skill_service.py -q --timeout=120
```
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 写实现**

Create `skills/service.py`:

```python
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
    """解析 SKILL.md → 存对象存储 → 注册 DB。name 重复抛 ValueError;缺 SKILL.md 抛 FileNotFoundError。"""
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
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_skill_service.py -q --timeout=120
```
Expected: 3 passed。

- [ ] **Step 5: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/src/agent_cloud_backend/skills/service.py services/backend/tests/test_skill_service.py && git commit -m "feat(backend): install_skill_from_dir service (parse -> store -> register)"
```

---

## Task 9: Skill API(list / install / upload / delete)

**Files:**
- Create: `services/backend/src/agent_cloud_backend/skills/deps.py`
- Create: `services/backend/src/agent_cloud_backend/api/skills.py`
- Modify: `services/backend/src/agent_cloud_backend/main.py`
- Modify: `services/backend/tests/conftest.py`
- Test: `services/backend/tests/test_skills_api.py`

- [ ] **Step 1: 写 deps**

Create `skills/deps.py`:

```python
from __future__ import annotations

from pathlib import Path

from agent_cloud_backend.config import get_settings
from agent_cloud_backend.skills.store import LocalObjectStore, ObjectStore

_store: ObjectStore | None = None


def get_object_store() -> ObjectStore:
    global _store
    if _store is None:
        _store = LocalObjectStore(Path(get_settings().object_store_root))
    return _store


def get_skill_registry_root() -> Path:
    # 内置 registry 随包发布:src/agent_cloud_backend/skill_registry/
    return Path(__file__).resolve().parent.parent / "skill_registry"
```

- [ ] **Step 2: 在 conftest 加 object store override + 注入到 client**

在 `tests/conftest.py` 顶部 import 区加:

```python
from agent_cloud_backend.skills.deps import get_object_store
from agent_cloud_backend.skills.store import LocalObjectStore
```

在 `override_sandbox_manager_fake` 函数之后加:

```python
def override_object_store(app, root):
    """让 skill 端点写到隔离的临时对象存储目录。"""
    store = LocalObjectStore(root)
    app.dependency_overrides[get_object_store] = lambda: store
    return store
```

把 `client` fixture 签名改为带 `tmp_path`,并在 `override_sandbox_manager_fake(app, engine)` 之后调用 override:

```python
@pytest_asyncio.fixture
async def client(engine, tmp_path) -> AsyncIterator[AsyncClient]:
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override
    override_sandbox_manager_fake(app, engine)
    override_object_store(app, tmp_path / "objstore")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

对 `client_noraise` fixture 同样:签名加 `tmp_path`,在 `override_sandbox_manager_fake(app, engine)` 后加 `override_object_store(app, tmp_path / "objstore")`。

- [ ] **Step 3: 写失败测试**

Create `tests/test_skills_api.py`:

```python
import io
import zipfile


async def _user(client, email):
    return (await client.post("/users", json={"email": email})).json()["id"]


def _zip_bytes(name="zippy", description="from zip"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            f"{name}/SKILL.md",
            f'---\nname: {name}\ndescription: "{description}"\n---\nbody\n',
        )
        zf.writestr(f"{name}/scripts/go.sh", "echo hi")
    buf.seek(0)
    return buf.getvalue()


async def test_install_from_registry_then_list(client):
    uid = await _user(client, "i1@e.com")
    r = await client.post("/skills/install", json={"user_id": uid, "name": "example-greeting"})
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "registry"
    r = await client.get(f"/skills?user_id={uid}")
    assert r.status_code == 200 and [s["name"] for s in r.json()] == ["example-greeting"]


async def test_install_unknown_registry_skill_404(client):
    uid = await _user(client, "i2@e.com")
    r = await client.post("/skills/install", json={"user_id": uid, "name": "does-not-exist"})
    assert r.status_code == 404


async def test_install_duplicate_409(client):
    uid = await _user(client, "i3@e.com")
    body = {"user_id": uid, "name": "example-greeting"}
    assert (await client.post("/skills/install", json=body)).status_code == 201
    assert (await client.post("/skills/install", json=body)).status_code == 409


async def test_upload_disabled_by_default_403(client):
    uid = await _user(client, "u1@e.com")
    r = await client.post(
        "/skills/upload",
        data={"user_id": uid},
        files={"file": ("s.zip", _zip_bytes(), "application/zip")},
    )
    assert r.status_code == 403


async def test_upload_enabled_201(client, monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_ALLOW_UPLOADED_ARCHIVES", "true")
    uid = await _user(client, "u2@e.com")
    r = await client.post(
        "/skills/upload",
        data={"user_id": uid},
        files={"file": ("s.zip", _zip_bytes(), "application/zip")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "uploaded" and r.json()["name"] == "zippy"


async def test_upload_zip_slip_rejected(client, monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_ALLOW_UPLOADED_ARCHIVES", "true")
    uid = await _user(client, "u3@e.com")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.sh", "echo pwned")
    buf.seek(0)
    r = await client.post(
        "/skills/upload",
        data={"user_id": uid},
        files={"file": ("s.zip", buf.getvalue(), "application/zip")},
    )
    assert r.status_code == 422


async def test_delete_skill(client):
    uid = await _user(client, "d1@e.com")
    sid = (
        await client.post("/skills/install", json={"user_id": uid, "name": "example-greeting"})
    ).json()["id"]
    assert (await client.delete(f"/skills/{sid}")).status_code == 204
    assert (await client.get(f"/skills?user_id={uid}")).json() == []
    assert (await client.delete(f"/skills/{sid}")).status_code == 404
```

- [ ] **Step 4: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_skills_api.py -q --timeout=120
```
Expected: FAIL（路由不存在,404/connection error）。

- [ ] **Step 5: 写 router**

Create `api/skills.py`:

```python
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
    entries = list(extract_dir.iterdir())
    if len(entries) == 1 and entries[0].is_dir() and (entries[0] / "SKILL.md").is_file():
        return entries[0]
    return None


@router.get("", response_model=list[SkillRead])
async def list_skills(user_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await SkillRepository(session).list_by_user(user_id)


@router.post("/install", response_model=SkillRead, status_code=status.HTTP_201_CREATED)
async def install_skill(
    body: SkillInstallRequest,
    session: AsyncSession = Depends(get_session),
    store: ObjectStore = Depends(get_object_store),
    registry_root: Path = Depends(get_skill_registry_root),
):
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
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
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
            raise HTTPException(status_code=422, detail=f"invalid archive: {e}")
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
            raise HTTPException(status_code=422, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
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
```

- [ ] **Step 6: 注册 router**

在 `main.py` 的 import 块把 `from agent_cloud_backend.api import (...)` 加上 `skills`,并在 `include_router` 的 tuple 里加 `skills`(放 `turn` 之后)。结果 import:

```python
from agent_cloud_backend.api import (
    agent_configs,
    context_documents,
    memory_entries,
    messages,
    sessions,
    skills,
    turn,
    users,
)
```

include tuple 改为:

```python
    for module in (
        users,
        agent_configs,
        sessions,
        messages,
        context_documents,
        memory_entries,
        turn,
        skills,
    ):
```

- [ ] **Step 7: 跑测试确认通过 + 全量回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q --timeout=120
```
Expected: 全绿（含 test_skills_api 7 项）。

- [ ] **Step 8: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/src/agent_cloud_backend/skills/deps.py services/backend/src/agent_cloud_backend/api/skills.py services/backend/src/agent_cloud_backend/main.py services/backend/tests/conftest.py services/backend/tests/test_skills_api.py && git commit -m "feat(backend): skill API (list/install/upload/delete)"
```

---

## Task 10: Agent skills enable API(GET / PUT)

**Files:**
- Create: `services/backend/src/agent_cloud_backend/api/agent_skills.py`
- Modify: `services/backend/src/agent_cloud_backend/main.py`
- Test: `services/backend/tests/test_agent_skills_api.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_agent_skills_api.py`:

```python
async def _user(client, email):
    return (await client.post("/users", json={"email": email})).json()["id"]


async def _agent(client, uid, name="a"):
    return (
        await client.post(
            "/agent-configs",
            json={"user_id": uid, "name": name, "model": "m", "provider": "p"},
        )
    ).json()["id"]


async def _install(client, uid, name):
    # 只有 example-greeting 在内置 registry;为多 skill 测试,上传 zip
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{name}/SKILL.md", f'---\nname: {name}\ndescription: "d"\n---\nx\n')
    buf.seek(0)
    return (
        await client.post(
            "/skills/upload",
            data={"user_id": uid},
            files={"file": ("s.zip", buf.getvalue(), "application/zip")},
        )
    ).json()["id"]


async def test_put_and_get_agent_skills(client, monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_ALLOW_UPLOADED_ARCHIVES", "true")
    uid = await _user(client, "as1@e.com")
    aid = await _agent(client, uid)
    s1 = await _install(client, uid, "alpha")
    s2 = await _install(client, uid, "beta")

    r = await client.put(f"/agent-configs/{aid}/skills", json={"skill_ids": [s1, s2]})
    assert r.status_code == 200, r.text
    assert {s["name"] for s in r.json()} == {"alpha", "beta"}

    # 替换:只留 alpha
    r = await client.put(f"/agent-configs/{aid}/skills", json={"skill_ids": [s1]})
    assert {s["name"] for s in r.json()} == {"alpha"}
    r = await client.get(f"/agent-configs/{aid}/skills")
    assert {s["name"] for s in r.json()} == {"alpha"}


async def test_put_unknown_agent_404(client):
    import uuid

    r = await client.put(f"/agent-configs/{uuid.uuid4()}/skills", json={"skill_ids": []})
    assert r.status_code == 404


async def test_put_rejects_other_users_skill(client, monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_ALLOW_UPLOADED_ARCHIVES", "true")
    owner = await _user(client, "owner@e.com")
    other = await _user(client, "other@e.com")
    aid = await _agent(client, owner)
    foreign = await _install(client, other, "foreign")
    r = await client.put(f"/agent-configs/{aid}/skills", json={"skill_ids": [foreign]})
    assert r.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_agent_skills_api.py -q --timeout=120
```
Expected: FAIL（路由不存在）。

- [ ] **Step 3: 写 router**

Create `api/agent_skills.py`:

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.skill import Skill
from agent_cloud_backend.repositories.skill import AgentSkillEnableRepository
from agent_cloud_backend.schemas.skill import AgentSkillsUpdate, SkillRead

router = APIRouter(prefix="/agent-configs", tags=["agent-skills"])


@router.get("/{agent_id}/skills", response_model=list[SkillRead])
async def list_agent_skills(agent_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await AgentSkillEnableRepository(session).list_enabled_for_agent(agent_id)


@router.put("/{agent_id}/skills", response_model=list[SkillRead])
async def set_agent_skills(
    agent_id: uuid.UUID,
    body: AgentSkillsUpdate,
    session: AsyncSession = Depends(get_session),
):
    agent = await session.get(AgentConfig, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent config not found")
    if body.skill_ids:
        result = await session.execute(
            select(Skill.id).where(
                Skill.id.in_(body.skill_ids), Skill.user_id == agent.user_id
            )
        )
        owned = {r[0] for r in result}
        missing = set(body.skill_ids) - owned
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"skills not owned by user: {sorted(str(m) for m in missing)}",
            )
    repo = AgentSkillEnableRepository(session)
    await repo.replace_enabled_set(agent_id, body.skill_ids)
    await session.commit()
    return await repo.list_enabled_for_agent(agent_id)
```

- [ ] **Step 4: 注册 router**

在 `main.py` import 块加 `agent_skills`,include tuple 末尾加 `agent_skills`(放 `skills` 之后)。

- [ ] **Step 5: 跑测试确认通过 + 全量回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q --timeout=120
```
Expected: 全绿。

- [ ] **Step 6: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/src/agent_cloud_backend/api/agent_skills.py services/backend/src/agent_cloud_backend/main.py services/backend/tests/test_agent_skills_api.py && git commit -m "feat(backend): per-agent skill enable API (GET/PUT)"
```

---

## Task 11: 收尾(全量回归 + lint)

**Files:** 无(仅验证)

- [ ] **Step 1: 全四套件回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q --timeout=120
cd /Users/wuhaowen/src/llm-agent/agent-cloud/packages/common && uv run pytest -q --timeout=120
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run pytest -q --timeout=120
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest -q --timeout=120
```
Expected: 四套件全绿（backend 在原 68 基础上 +约 30 项 skill 测试)。

- [ ] **Step 2: ruff**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && uv run ruff check services/backend
```
Expected: `All checks passed!`(如有 import 排序等问题,`uv run ruff check --fix services/backend` 后重跑)。

- [ ] **Step 3: 最终 commit(如 ruff --fix 产生改动)**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add -A services/backend && git commit -m "chore(backend): ruff clean for skill data layer"
```
(若无改动则跳过。)

---

## Self-Review(对照 spec §12)

- **§12.1 Scope**(用户级安装 + per-agent 启用):Task 2 模型 `skills`(user_id)+ `agent_skill_enables`;Task 10 PUT/GET。✔
- **§12.2 数据模型**:Task 2/3(表 + 迁移),package_ref 指对象存储。✔
- **§12.3 安装/卸载 API**:`GET /skills`、`POST /skills/install`(registry)、`POST /skills/upload`(zip,受 `allow_uploaded_archives` 开关)、`DELETE /skills/{id}`、`PUT /agent-configs/{id}/skills`。✔
- **§11 供应链/安全**:upload 开关默认关 + zip-slip 防护(Task 9);name 路径校验(Task 5);跨用户启用拒绝(Task 10)。✔
- **install:校验 → 存对象存储 → 注册 Postgres**:Task 8 `install_skill_from_dir`。✔(「失效该用户沙箱的 skill 缓存」属于物化/缓存,留 **Plan 5b**。)
- **留给 Plan 5b**:回合时 enabled skill 元数据注入 run_turn `context.skills` → worker `<available_skills>` prompt;物化进沙箱 `/skills/`;install/uninstall 缓存失效;端到端读 SKILL.md 跑脚本。本计划不碰 worker/sandbox/common。

类型一致性核对:`SkillRepository.get_by_user_and_name`、`AgentSkillEnableRepository.{set_enabled,replace_enabled_set,list_enabled_for_agent}`、`install_skill_from_dir(*, user_id, src_dir, source, repo, store)`、`skill_package_ref(user_id, name)`、`get_object_store`/`get_skill_registry_root`、schema `SkillRead/SkillInstallRequest/AgentSkillsUpdate` —— 跨任务引用一致。✔
