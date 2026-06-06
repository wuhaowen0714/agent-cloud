# Plan 5a: Skill 数据层 + 对象存储 + 后端 CRUD/enable API 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 skill 系统建数据底座——`skills` / `agent_skill_enables` 两表、对象存储抽象、SKILL.md 解析、安装(内置 registry + 上传 zip)/卸载/per-agent 启用的后端 API。

**Architecture:** 纯后端,沿用现有 models/repositories/schemas/api 分层。skill 包文件存对象存储(`ObjectStore` Protocol + `LocalObjectStore` 本地替身,对应生产 S3),元数据存 Postgres。`install`(从仓库内置 registry)与 `upload`(用户 zip,受开关控制)共用「解析 SKILL.md → 存对象存储 → 注册 DB」逻辑。回合时的元数据注入 + 物化进沙箱是 **Plan 5b**,本计划不碰 worker/sandbox/common。

**Tech Stack:** FastAPI、SQLAlchemy 2.0 async、Alembic、Pydantic v2、PyYAML(frontmatter)、python-multipart(上传)、pytest + testcontainers[postgres]。

---

## 测试约定(每个任务都遵守)

- **backend 测试必须用** `TESTCONTAINERS_RYUK_DISABLED=true`(本机 Docker 环境下 Ryuk 会中途杀测试容器导致 asyncpg 永久挂起)+ `--timeout=120`。
- 每条命令都用**绝对路径 `cd`**(shell cwd 跨命令保持,子 shell `(cd ...)` 不改父 cwd)。
- 单测命令样板:
  ```bash
  cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/<file>.py -q --timeout=120
  ```
- 每个任务结尾跑一次 backend 全量回归(见各 Task 的最后一步)。

## 文件结构

**新建:**
- `services/backend/src/agent_cloud_backend/models/skill.py` — `Skill` + `AgentSkillEnable` ORM
- `services/backend/src/agent_cloud_backend/repositories/skill.py` — `SkillRepository` + `AgentSkillEnableRepository`
- `services/backend/src/agent_cloud_backend/schemas/skill.py` — Pydantic schema
- `services/backend/src/agent_cloud_backend/skills/__init__.py`
- `services/backend/src/agent_cloud_backend/skills/store.py` — `ObjectStore` + `LocalObjectStore`
- `services/backend/src/agent_cloud_backend/skills/manifest.py` — SKILL.md frontmatter 解析
- `services/backend/src/agent_cloud_backend/skills/service.py` — `install_skill_from_dir`
- `services/backend/src/agent_cloud_backend/skills/deps.py` — `get_object_store` / `get_skill_registry_root`
- `services/backend/src/agent_cloud_backend/api/skills.py` — `/skills` router
- `services/backend/src/agent_cloud_backend/api/agent_skills.py` — `/agent-configs/{id}/skills` router
- `services/backend/src/agent_cloud_backend/skill_registry/example-greeting/SKILL.md` + `scripts/greet.sh` — 内置 registry 示例
- `services/backend/alembic/versions/<rev>_add_skills_tables.py` — 迁移
- 测试:`tests/test_object_store.py`、`tests/test_skill_manifest.py`、`tests/test_repo_skills.py`、`tests/test_skill_service.py`、`tests/test_skills_api.py`、`tests/test_agent_skills_api.py`

**修改:**
- `services/backend/pyproject.toml` — 加 `pyyaml`、`python-multipart`
- `services/backend/src/agent_cloud_backend/config.py` — 加 `object_store_root`、`allow_uploaded_archives`
- `services/backend/src/agent_cloud_backend/models/__init__.py` — 导出新模型
- `services/backend/src/agent_cloud_backend/main.py` — 注册两个 router
- `services/backend/tests/conftest.py` — object store override
- `services/backend/tests/test_models_create.py`、`tests/test_migration.py` — 覆盖新表

---

## Task 1: 依赖 + config

**Files:**
- Modify: `services/backend/pyproject.toml`
- Modify: `services/backend/src/agent_cloud_backend/config.py`

- [ ] **Step 1: 加运行时依赖**

在 `pyproject.toml` 的 `dependencies` 列表(`pydantic-settings` 之后)加两行:

```toml
    "pyyaml",
    "python-multipart",
```

- [ ] **Step 2: 同步锁文件**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && uv lock
```
Expected: `uv.lock` 更新,包含 pyyaml / python-multipart。

- [ ] **Step 3: 扩展 config**

在 `config.py` 的 `Settings` 内,`sandbox_base_root` 一行之后加:

```python
    object_store_root: str = "/tmp/agent-cloud-object-store"
    allow_uploaded_archives: bool = False
```

- [ ] **Step 4: 冒烟验证导入**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run python -c "import yaml, multipart; from agent_cloud_backend.config import get_settings; s=get_settings(); print(s.object_store_root, s.allow_uploaded_archives)"
```
Expected: 打印 `/tmp/agent-cloud-object-store False`,无 ImportError。

- [ ] **Step 5: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/pyproject.toml uv.lock services/backend/src/agent_cloud_backend/config.py && git commit -m "feat(backend): skill deps (pyyaml, multipart) + object store config"
```

---

## Task 2: ORM 模型 Skill + AgentSkillEnable

**Files:**
- Create: `services/backend/src/agent_cloud_backend/models/skill.py`
- Modify: `services/backend/src/agent_cloud_backend/models/__init__.py`
- Test: `services/backend/tests/test_models_create.py`

- [ ] **Step 1: 写失败测试**

把 `tests/test_models_create.py` 的 `expected` 集合改为(加最后两项):

```python
    expected = {
        "users",
        "agent_configs",
        "sessions",
        "messages",
        "context_documents",
        "memory_entries",
        "skills",
        "agent_skill_enables",
    }
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_models_create.py -q --timeout=120
```
Expected: FAIL（`skills` / `agent_skill_enables` 不在已建表中）。

- [ ] **Step 3: 写模型**

Create `models/skill.py`:

```python
import uuid

from sqlalchemy import Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud_backend.models.base import Base, TimestampMixin, uuid_pk


class Skill(Base, TimestampMixin):
    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(nullable=False)  # registry | uploaded
    version: Mapped[str] = mapped_column(nullable=False, default="0.0.0")
    requires: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    package_ref: Mapped[str] = mapped_column(nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_skill_user_name"),)


class AgentSkillEnable(Base):
    __tablename__ = "agent_skill_enables"

    agent_config_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_configs.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
```

- [ ] **Step 4: 注册到 models/__init__.py**

把 `models/__init__.py` 改为(加 import + __all__ 项):

```python
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.base import Base
from agent_cloud_backend.models.context_document import ContextDocument
from agent_cloud_backend.models.memory_entry import MemoryEntry
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.models.sandbox_registry import SandboxRegistry
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.models.skill import AgentSkillEnable, Skill
from agent_cloud_backend.models.user import User

__all__ = [
    "Base",
    "User",
    "AgentConfig",
    "Session",
    "Message",
    "ContextDocument",
    "MemoryEntry",
    "SandboxRegistry",
    "Skill",
    "AgentSkillEnable",
]
```

- [ ] **Step 5: 跑测试确认通过 + 全量回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q --timeout=120
```
Expected: 全绿(原有 + test_models_create 现含两新表）。

- [ ] **Step 6: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/src/agent_cloud_backend/models/skill.py services/backend/src/agent_cloud_backend/models/__init__.py services/backend/tests/test_models_create.py && git commit -m "feat(backend): Skill + AgentSkillEnable ORM models"
```

---

## Task 3: Alembic 迁移

**Files:**
- Create: `services/backend/alembic/versions/7a1b2c3d4e5f_add_skills_tables.py`
- Test: `services/backend/tests/test_migration.py`

- [ ] **Step 1: 扩展迁移测试**

在 `tests/test_migration.py` 里,把表断言集合加两项,并加 skills 唯一索引断言。改 `assert {...}.issubset(tables)` 块为:

```python
    assert {
        "users",
        "agent_configs",
        "sessions",
        "messages",
        "context_documents",
        "memory_entries",
        "sandbox_registry",
        "skills",
        "agent_skill_enables",
    }.issubset(tables)
    assert "alembic_version" in tables
    assert "uq_active_sandbox_per_user" in indexes
```

并在收集 `indexes` 之后(同一个 `with engine.connect()` 块内,`idx_rows` 之后)追加 skills 索引收集:

```python
        skill_idx_rows = conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname='public' AND tablename='skills'"
            )
        )
        skill_indexes = {r[0] for r in skill_idx_rows}
```

并在末尾加:

```python
    assert "uq_skill_user_name" in skill_indexes
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_migration.py -q --timeout=120
```
Expected: FAIL（迁移还没建 skills 表）。

- [ ] **Step 3: 手写迁移文件**

Create `alembic/versions/7a1b2c3d4e5f_add_skills_tables.py`:

```python
"""add skills + agent_skill_enables

Revision ID: 7a1b2c3d4e5f
Revises: 118b49942e83
Create Date: 2026-06-07 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7a1b2c3d4e5f"
down_revision: str | Sequence[str] | None = "118b49942e83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("requires", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("package_ref", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_skill_user_name"),
    )
    op.create_index(op.f("ix_skills_user_id"), "skills", ["user_id"], unique=False)
    op.create_table(
        "agent_skill_enables",
        sa.Column("agent_config_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["agent_config_id"], ["agent_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_config_id", "skill_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("agent_skill_enables")
    op.drop_index(op.f("ix_skills_user_id"), table_name="skills")
    op.drop_table("skills")
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q --timeout=120
```
Expected: 全绿（test_migration 现确认 skills/agent_skill_enables 表 + uq_skill_user_name 索引）。

- [ ] **Step 5: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/alembic/versions/7a1b2c3d4e5f_add_skills_tables.py services/backend/tests/test_migration.py && git commit -m "feat(backend): alembic migration for skills tables"
```

---

## Task 4: 对象存储抽象

**Files:**
- Create: `services/backend/src/agent_cloud_backend/skills/__init__.py`(空文件)
- Create: `services/backend/src/agent_cloud_backend/skills/store.py`
- Test: `services/backend/tests/test_object_store.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_object_store.py`:

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_object_store.py -q --timeout=120
```
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 写实现**

Create `skills/__init__.py`(空)。Create `skills/store.py`:

```python
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol


class ObjectStore(Protocol):
    """skill 包对象存储抽象。生产用 S3;本仓库用 LocalObjectStore。"""

    def put_dir(self, prefix: str, src_dir: Path) -> None: ...
    def get_dir(self, prefix: str, dst_dir: Path) -> None: ...
    def delete_prefix(self, prefix: str) -> None: ...
    def exists(self, prefix: str) -> bool: ...


class LocalObjectStore:
    """本地文件系统替身:prefix → root/prefix 目录。"""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _path(self, prefix: str) -> Path:
        root = self._root.resolve()
        p = (self._root / prefix).resolve()
        if p != root and root not in p.parents:
            raise ValueError(f"prefix escapes object store root: {prefix!r}")
        return p

    def put_dir(self, prefix: str, src_dir: Path) -> None:
        dst = self._path(prefix)
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_dir, dst)

    def get_dir(self, prefix: str, dst_dir: Path) -> None:
        src = self._path(prefix)
        if not src.exists():
            raise FileNotFoundError(prefix)
        dst = Path(dst_dir)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)

    def delete_prefix(self, prefix: str) -> None:
        p = self._path(prefix)
        if p.exists():
            shutil.rmtree(p)

    def exists(self, prefix: str) -> bool:
        return self._path(prefix).exists()
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_object_store.py -q --timeout=120
```
Expected: 5 passed。

- [ ] **Step 5: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/src/agent_cloud_backend/skills/__init__.py services/backend/src/agent_cloud_backend/skills/store.py services/backend/tests/test_object_store.py && git commit -m "feat(backend): ObjectStore abstraction + LocalObjectStore"
```

---

## Task 5: SKILL.md frontmatter 解析

**Files:**
- Create: `services/backend/src/agent_cloud_backend/skills/manifest.py`
- Test: `services/backend/tests/test_skill_manifest.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_skill_manifest.py`:

```python
import pytest

from agent_cloud_backend.skills.manifest import (
    SkillManifest,
    SkillManifestError,
    parse_skill_md,
)

VALID = """---
name: example-greeting
description: "Print a greeting."
requires:
  bins: [bash]
version: "1.2.3"
---

# example-greeting
body
"""


def test_parse_valid():
    m = parse_skill_md(VALID)
    assert m == SkillManifest(
        name="example-greeting",
        description="Print a greeting.",
        requires={"bins": ["bash"]},
        version="1.2.3",
    )


def test_defaults_when_optional_missing():
    m = parse_skill_md('---\nname: a\ndescription: d\n---\nx\n')
    assert m.requires == {}
    assert m.version == "0.0.0"


def test_missing_frontmatter():
    with pytest.raises(SkillManifestError):
        parse_skill_md("# no frontmatter\n")


def test_bad_yaml():
    with pytest.raises(SkillManifestError):
        parse_skill_md("---\nname: [unclosed\n---\nx\n")


@pytest.mark.parametrize(
    "name",
    ["", "Bad Name", "../evil", "a/b", "..", "UPPER", "with space"],
)
def test_invalid_names_rejected(name):
    with pytest.raises(SkillManifestError):
        parse_skill_md(f'---\nname: "{name}"\ndescription: d\n---\nx\n')


def test_missing_description():
    with pytest.raises(SkillManifestError):
        parse_skill_md("---\nname: ok\n---\nx\n")


def test_requires_must_be_mapping():
    with pytest.raises(SkillManifestError):
        parse_skill_md("---\nname: ok\ndescription: d\nrequires: [bash]\n---\nx\n")
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_skill_manifest.py -q --timeout=120
```
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 写实现**

Create `skills/manifest.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class SkillManifestError(ValueError):
    """SKILL.md 缺失/不合法。"""


@dataclass
class SkillManifest:
    name: str
    description: str
    requires: dict = field(default_factory=dict)
    version: str = "0.0.0"


def parse_skill_md(text: str) -> SkillManifest:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise SkillManifestError("SKILL.md missing YAML frontmatter")
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        raise SkillManifestError(f"invalid YAML frontmatter: {e}") from e
    if not isinstance(data, dict):
        raise SkillManifestError("frontmatter must be a mapping")

    name = data.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name) or ".." in name:
        raise SkillManifestError(f"invalid or missing skill name: {name!r}")

    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        raise SkillManifestError("missing skill description")

    requires = data.get("requires", {})
    if not isinstance(requires, dict):
        raise SkillManifestError("requires must be a mapping if present")

    version = data.get("version", "0.0.0")
    if not isinstance(version, str):
        raise SkillManifestError("version must be a string")

    return SkillManifest(
        name=name, description=description, requires=requires, version=version
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_skill_manifest.py -q --timeout=120
```
Expected: 全 passed（含参数化非法 name）。

- [ ] **Step 5: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/src/agent_cloud_backend/skills/manifest.py services/backend/tests/test_skill_manifest.py && git commit -m "feat(backend): SKILL.md frontmatter parser with name/path validation"
```

---

> **后续 Task 6–11 见同目录续写文件 `2026-06-07-plan-5a-skill-data-layer-part2.md`。**(本文件为保持可读分两段;执行时按顺序连读。)
