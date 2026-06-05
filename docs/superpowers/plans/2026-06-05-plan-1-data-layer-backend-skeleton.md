# Plan 1: 数据层 + 后端骨架 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立无状态 Agent Cloud 后端的持久化地基:6 个核心实体的数据模型、迁移,以及对应的 CRUD API,全部用真实 Postgres 测试。

**Architecture:** Python + FastAPI 的无状态后端服务,SQLAlchemy 2.0 (async) 访问 Postgres,Alembic 管理迁移。分层:`models`(ORM)→ `repositories`(数据访问)→ `api`(HTTP 路由),`schemas`(Pydantic 出入参)横切。本计划不含 agent/worker/sandbox(见后续 Plan),只产出可独立运行、可测试的后端 + 数据层。

**Tech Stack:** Python 3.12、uv(包管理)、FastAPI、SQLAlchemy 2.0 async + asyncpg、Alembic、Pydantic v2、pytest + pytest-asyncio + httpx + testcontainers[postgres]、ruff。

参考设计 spec:`docs/superpowers/specs/2026-06-05-stateless-agent-cloud-design.md`(§5 数据模型)。

---

## 范围与实体

本计划实现 6 个核心实体(spec §5.1):**User、AgentConfig、Session、Message、context_documents、memory_entries**。

明确**不在本计划**(留给后续 Plan,避免 YAGNI):
- `skills` / `agent_skill_enables`(Plan 5)、`SandboxRegistry`(Plan 4)。
- `memory_entries.embedding` 向量列:本计划**不加物理列**;读取接口 `list_for_context(scope, owner_id, limit)` 作为未来从"取最近 N 条"切换到"向量 top-k"的接缝(spec §5.1 预留)。
- 认证鉴权(后续);本计划 API 不加 auth,仅做 CRUD 骨架。

## File Structure

```
agent-cloud/
  pyproject.toml                      # 项目与依赖(uv)
  alembic.ini                         # Alembic 配置
  alembic/env.py                      # Alembic 运行环境(读 models metadata)
  alembic/versions/                   # 迁移脚本
  src/agent_cloud/
    __init__.py
    config.py                         # Settings(DATABASE_URL 等)
    db.py                             # async engine、session factory、Base
    main.py                           # FastAPI app、include routers、/health
    models/{base,user,agent_config,session,message,context_document,memory_entry}.py
    schemas/{user,agent_config,session,message,context_document,memory_entry}.py
    repositories/{base,user,agent_config,session,message,context_document,memory_entry}.py
    api/{deps,users,agent_configs,sessions,context_documents,memory_entries,messages}.py
  tests/
    conftest.py                       # testcontainer Postgres + app + async client fixtures
    test_health.py
    test_repo_user.py
    test_repo_entities.py             # 其余实体仓库
    test_api.py                       # 端到端 API
```

每个文件单一职责:`models/*` 只定义 ORM 表;`schemas/*` 只定义出入参;`repositories/*` 只做数据访问;`api/*` 只做 HTTP 编排。

---

### Task 1: 项目脚手架 + 配置 + /health

**Files:**
- Create: `pyproject.toml`, `src/agent_cloud/__init__.py`, `src/agent_cloud/config.py`, `src/agent_cloud/main.py`
- Test: `tests/test_health.py`, `tests/__init__.py`

- [ ] **Step 1: 初始化项目与依赖**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
uv init --bare --python 3.12
uv add fastapi "uvicorn[standard]" "sqlalchemy[asyncio]>=2.0" asyncpg alembic "pydantic>=2" pydantic-settings
uv add --dev pytest pytest-asyncio httpx "testcontainers[postgres]" ruff
```
Expected: 生成 `pyproject.toml` 与 `uv.lock`,依赖安装成功。

- [ ] **Step 2: 写配置**

Create `src/agent_cloud/config.py`:
```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_CLOUD_", env_file=".env")

    # 形如 postgresql+asyncpg://user:pass@host:5432/dbname
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/agent_cloud"


def get_settings() -> Settings:
    return Settings()
```

Create empty `src/agent_cloud/__init__.py` and `tests/__init__.py`.

- [ ] **Step 3: 写 FastAPI app 骨架 + /health**

Create `src/agent_cloud/main.py`:
```python
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Agent Cloud Backend")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 4: 写 /health 失败测试**

Create `tests/test_health.py`:
```python
import pytest
from httpx import ASGITransport, AsyncClient

from agent_cloud.main import create_app


@pytest.mark.asyncio
async def test_health_ok():
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

Add to `pyproject.toml` (pytest asyncio 自动模式):
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["src"]
```

- [ ] **Step 5: 运行测试**

Run: `uv run pytest tests/test_health.py -v`
Expected: PASS(1 passed)。

- [ ] **Step 6: 提交**

```bash
git add pyproject.toml uv.lock src/agent_cloud/__init__.py src/agent_cloud/config.py src/agent_cloud/main.py tests/__init__.py tests/test_health.py
git commit -m "feat: scaffold FastAPI backend with health endpoint"
```

---

### Task 2: DB 基础(engine / session / Base)

**Files:**
- Create: `src/agent_cloud/db.py`, `src/agent_cloud/models/__init__.py`, `src/agent_cloud/models/base.py`

- [ ] **Step 1: 写 Base 与公共 mixin**

Create `src/agent_cloud/models/base.py`:
```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 2: 写 engine / session factory / 依赖**

Create `src/agent_cloud/db.py`:
```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from agent_cloud.config import get_settings

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, future=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session
```

Create `src/agent_cloud/models/__init__.py`:
```python
from agent_cloud.models.base import Base

__all__ = ["Base"]
```

- [ ] **Step 3: 提交**

```bash
git add src/agent_cloud/db.py src/agent_cloud/models/__init__.py src/agent_cloud/models/base.py
git commit -m "feat: add async db engine, session factory, and ORM base"
```

---

### Task 3: ORM 模型(6 实体)

**Files:**
- Create: `src/agent_cloud/models/{user,agent_config,session,message,context_document,memory_entry}.py`
- Modify: `src/agent_cloud/models/__init__.py`
- Test: `tests/conftest.py`, `tests/test_models_create.py`

- [ ] **Step 1: User 模型**

Create `src/agent_cloud/models/user.py`:
```python
import uuid

from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud.models.base import Base, TimestampMixin, uuid_pk


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
```

- [ ] **Step 2: AgentConfig 模型**

Create `src/agent_cloud/models/agent_config.py`:
```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud.models.base import Base, TimestampMixin, uuid_pk


class AgentConfig(Base, TimestampMixin):
    __tablename__ = "agent_configs"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(nullable=False)
    model: Mapped[str] = mapped_column(nullable=False)
    provider: Mapped[str] = mapped_column(nullable=False)
    thinking_level: Mapped[str | None] = mapped_column(nullable=True)
    enabled_tools: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    permissions: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    key_ref: Mapped[str | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [ ] **Step 3: Session 模型**

Create `src/agent_cloud/models/session.py`:
```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud.models.base import Base, TimestampMixin, uuid_pk


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    agent_config_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_configs.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    title: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(default="idle", nullable=False)  # idle | running
    work_subdir: Mapped[str] = mapped_column(nullable=False)
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 4: Message 模型**

Create `src/agent_cloud/models/message.py`:
```python
import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud.models.base import Base, TimestampMixin, uuid_pk


class Message(Base, TimestampMixin):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_message_session_seq"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    seq: Mapped[int] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(nullable=False)  # user | assistant | tool
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    model: Mapped[str | None] = mapped_column(nullable=True)
    tokens: Mapped[int | None] = mapped_column(nullable=True)
```

- [ ] **Step 5: context_documents 模型**

Create `src/agent_cloud/models/context_document.py`:
```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud.models.base import Base, uuid_pk


class ContextDocument(Base):
    __tablename__ = "context_documents"
    __table_args__ = (
        UniqueConstraint("scope", "type", "owner_id", name="uq_ctxdoc_scope_type_owner"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    scope: Mapped[str] = mapped_column(nullable=False)  # user | agent
    type: Mapped[str] = mapped_column(nullable=False)   # USER | AGENTS | SOUL | ...
    owner_id: Mapped[uuid.UUID] = mapped_column(index=True, nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [ ] **Step 6: memory_entries 模型**

Create `src/agent_cloud/models/memory_entry.py`:
```python
import uuid

from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud.models.base import Base, TimestampMixin, uuid_pk

# 注:embedding 向量列在引入向量检索的后续 Plan 中添加;此处不加物理列。


class MemoryEntry(Base, TimestampMixin):
    __tablename__ = "memory_entries"

    id: Mapped[uuid.UUID] = uuid_pk()
    scope: Mapped[str] = mapped_column(index=True, nullable=False)  # user | agent
    owner_id: Mapped[uuid.UUID] = mapped_column(index=True, nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
```

- [ ] **Step 7: 汇总到 models/__init__.py**

Replace `src/agent_cloud/models/__init__.py`:
```python
from agent_cloud.models.agent_config import AgentConfig
from agent_cloud.models.base import Base
from agent_cloud.models.context_document import ContextDocument
from agent_cloud.models.memory_entry import MemoryEntry
from agent_cloud.models.message import Message
from agent_cloud.models.session import Session
from agent_cloud.models.user import User

__all__ = [
    "Base",
    "User",
    "AgentConfig",
    "Session",
    "Message",
    "ContextDocument",
    "MemoryEntry",
]
```

- [ ] **Step 8: 写 testcontainers fixture(真实 Postgres)**

Create `tests/conftest.py`:
```python
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from agent_cloud.api.deps import get_session
from agent_cloud.main import create_app
from agent_cloud.models import Base


@pytest.fixture(scope="session")
def pg_url() -> AsyncIterator[str]:
    with PostgresContainer("postgres:16", driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest_asyncio.fixture
async def engine(pg_url: str):
    eng = create_async_engine(pg_url, future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s


@pytest_asyncio.fixture
async def client(engine) -> AsyncIterator[AsyncClient]:
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

> 注:`tests/conftest.py` 引用了尚未创建的 `agent_cloud.api.deps`;Step 9 的测试只用 `session`/`engine` fixture,`client` fixture 在 Task 8 才被使用。为避免导入失败,本步同时创建占位 `api/deps.py`(见下)。

Create `src/agent_cloud/api/__init__.py`(空文件)与 `src/agent_cloud/api/deps.py`:
```python
from agent_cloud.db import get_session

__all__ = ["get_session"]
```

- [ ] **Step 9: 写"建表成功"测试**

Create `tests/test_models_create.py`:
```python
from sqlalchemy import text


async def test_all_tables_created(engine):
    expected = {
        "users",
        "agent_configs",
        "sessions",
        "messages",
        "context_documents",
        "memory_entries",
    }
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        tables = {r[0] for r in rows}
    assert expected.issubset(tables)
```

- [ ] **Step 10: 运行测试**

Run: `uv run pytest tests/test_models_create.py -v`
Expected: PASS(testcontainers 拉起 Postgres,`create_all` 建出 6 张表)。
> 首次运行会拉取 `postgres:16` 镜像,需要 Docker 在运行。

- [ ] **Step 11: 提交**

```bash
git add src/agent_cloud/models tests/conftest.py tests/test_models_create.py src/agent_cloud/api/__init__.py src/agent_cloud/api/deps.py
git commit -m "feat: add ORM models for 6 core entities with testcontainer fixtures"
```

---

### Task 4: Alembic 迁移

**Files:**
- Create: `alembic.ini`, `alembic/env.py`, `alembic/versions/*` (autogenerated)
- Test: `tests/test_migration.py`

- [ ] **Step 1: 初始化 Alembic**

Run:
```bash
uv run alembic init -t async alembic
```
Expected: 生成 `alembic.ini` 与 `alembic/`(async 模板)。

- [ ] **Step 2: 接线 env.py 到我们的 metadata 与配置**

Replace `alembic/env.py` 的 config/target 部分为以下完整文件:
```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from agent_cloud.config import get_settings
from agent_cloud.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_settings().database_url, future=True)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Step 3: 用本地 Postgres 生成初始迁移**

先起一个本地库(开发用):
```bash
docker run -d --name agent-cloud-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=agent_cloud -p 5432:5432 postgres:16
uv run alembic revision --autogenerate -m "initial schema"
```
Expected: 在 `alembic/versions/` 生成一个迁移,内含 6 张表的 `create_table`。打开确认无误(6 张表都在)。

- [ ] **Step 4: 写迁移测试(对干净库 upgrade 后 6 表存在)**

Create `tests/test_migration.py`:
```python
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def test_alembic_upgrade_creates_schema(pg_url: str):
    sync_url = pg_url.replace("+asyncpg", "")  # alembic 同步连接
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", sync_url)
    # 让 env.py 用同一个库:通过环境变量覆盖
    import os

    os.environ["AGENT_CLOUD_DATABASE_URL"] = pg_url
    command.upgrade(cfg, "head")

    engine = create_engine(sync_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        )
        tables = {r[0] for r in rows}
    assert {"users", "agent_configs", "sessions", "messages",
            "context_documents", "memory_entries"}.issubset(tables)
    # alembic 版本表也应存在
    assert "alembic_version" in tables
```
> 该测试用独立的 testcontainer(`pg_url` session fixture,无 `engine` fixture 的 create_all),验证迁移自身能建出 schema。需安装同步驱动:`uv add --dev psycopg2-binary`。

- [ ] **Step 5: 运行测试**

Run: `uv add --dev psycopg2-binary && uv run pytest tests/test_migration.py -v`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add alembic.ini alembic/ tests/test_migration.py pyproject.toml uv.lock
git commit -m "feat: add alembic async migrations with initial schema"
```

---

### Task 5: Pydantic Schemas

**Files:**
- Create: `src/agent_cloud/schemas/{__init__,user,agent_config,session,message,context_document,memory_entry}.py`

> 模式:每实体一组 `XCreate`(入参)/ `XRead`(出参)/(可选)`XUpdate`。`XRead` 用 `from_attributes=True` 以便从 ORM 转换。

- [ ] **Step 1: User schemas**

Create `src/agent_cloud/schemas/user.py`:
```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserCreate(BaseModel):
    email: EmailStr


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    created_at: datetime
```
> 需要 email 校验:`uv add "pydantic[email]"`。

- [ ] **Step 2: AgentConfig schemas**

Create `src/agent_cloud/schemas/agent_config.py`:
```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AgentConfigCreate(BaseModel):
    user_id: uuid.UUID
    name: str
    model: str
    provider: str
    thinking_level: str | None = None
    enabled_tools: list[str] = []
    permissions: dict = {}
    key_ref: str | None = None


class AgentConfigUpdate(BaseModel):
    name: str | None = None
    model: str | None = None
    provider: str | None = None
    thinking_level: str | None = None
    enabled_tools: list[str] | None = None
    permissions: dict | None = None
    key_ref: str | None = None


class AgentConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    model: str
    provider: str
    thinking_level: str | None
    enabled_tools: list[str]
    permissions: dict
    key_ref: str | None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 3: Session schemas**

Create `src/agent_cloud/schemas/session.py`:
```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionCreate(BaseModel):
    user_id: uuid.UUID
    agent_config_id: uuid.UUID
    title: str | None = None


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    agent_config_id: uuid.UUID
    title: str | None
    status: str
    work_subdir: str
    created_at: datetime
    last_active_at: datetime
```

- [ ] **Step 4: Message schemas**

Create `src/agent_cloud/schemas/message.py`:
```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MessageCreate(BaseModel):
    role: str  # user | assistant | tool
    content: dict
    model: str | None = None
    tokens: int | None = None


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    session_id: uuid.UUID
    seq: int
    role: str
    content: dict
    model: str | None
    tokens: int | None
    created_at: datetime
```

- [ ] **Step 5: ContextDocument schemas**

Create `src/agent_cloud/schemas/context_document.py`:
```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContextDocumentUpsert(BaseModel):
    scope: str   # user | agent
    type: str    # USER | AGENTS | SOUL | IDENTITY | TOOLS | HEARTBEAT | BOOTSTRAP
    owner_id: uuid.UUID
    content: str


class ContextDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    scope: str
    type: str
    owner_id: uuid.UUID
    content: str
    updated_at: datetime
```

- [ ] **Step 6: MemoryEntry schemas**

Create `src/agent_cloud/schemas/memory_entry.py`:
```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MemoryAppend(BaseModel):
    scope: str  # user | agent
    owner_id: uuid.UUID
    content: str
    source_session_id: uuid.UUID | None = None


class MemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    scope: str
    owner_id: uuid.UUID
    content: str
    source_session_id: uuid.UUID | None
    created_at: datetime
```

Create empty `src/agent_cloud/schemas/__init__.py`.

- [ ] **Step 7: 提交**

```bash
git add src/agent_cloud/schemas pyproject.toml uv.lock
git commit -m "feat: add pydantic schemas for core entities"
```

---

### Task 6: BaseRepository + User 仓库(含测试)

**Files:**
- Create: `src/agent_cloud/repositories/{__init__,base,user}.py`
- Test: `tests/test_repo_user.py`

- [ ] **Step 1: 写 User 仓库失败测试**

Create `tests/test_repo_user.py`:
```python
import uuid

import pytest

from agent_cloud.models.user import User
from agent_cloud.repositories.user import UserRepository


async def test_create_and_get_user(session):
    repo = UserRepository(session)
    user = await repo.create(User(email="a@example.com"))
    await session.commit()

    fetched = await repo.get(user.id)
    assert fetched is not None
    assert fetched.email == "a@example.com"


async def test_get_missing_returns_none(session):
    repo = UserRepository(session)
    assert await repo.get(uuid.uuid4()) is None


async def test_list_users(session):
    repo = UserRepository(session)
    await repo.create(User(email="a@example.com"))
    await repo.create(User(email="b@example.com"))
    await session.commit()
    users = await repo.list()
    assert {u.email for u in users} == {"a@example.com", "b@example.com"}
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/test_repo_user.py -v`
Expected: FAIL(`ModuleNotFoundError: agent_cloud.repositories.user`)。

- [ ] **Step 3: 写 BaseRepository**

Create `src/agent_cloud/repositories/base.py`:
```python
import uuid
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, obj: ModelT) -> ModelT:
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get(self, obj_id: uuid.UUID) -> ModelT | None:
        return await self.session.get(self.model, obj_id)

    async def list(self) -> list[ModelT]:
        result = await self.session.execute(select(self.model))
        return list(result.scalars().all())

    async def delete(self, obj: ModelT) -> None:
        await self.session.delete(obj)
        await self.session.flush()
```

- [ ] **Step 4: 写 UserRepository**

Create `src/agent_cloud/repositories/user.py`:
```python
from sqlalchemy import select

from agent_cloud.models.user import User
from agent_cloud.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()
```

Create empty `src/agent_cloud/repositories/__init__.py`.

- [ ] **Step 5: 运行,确认通过**

Run: `uv run pytest tests/test_repo_user.py -v`
Expected: PASS(3 passed)。

- [ ] **Step 6: 提交**

```bash
git add src/agent_cloud/repositories/__init__.py src/agent_cloud/repositories/base.py src/agent_cloud/repositories/user.py tests/test_repo_user.py
git commit -m "feat: add BaseRepository and UserRepository"
```

---

### Task 7: 其余仓库(含特定查询与测试)

**Files:**
- Create: `src/agent_cloud/repositories/{agent_config,session,message,context_document,memory_entry}.py`
- Test: `tests/test_repo_entities.py`

- [ ] **Step 1: 写失败测试(覆盖各仓库的关键行为)**

Create `tests/test_repo_entities.py`:
```python
from agent_cloud.models.agent_config import AgentConfig
from agent_cloud.models.context_document import ContextDocument
from agent_cloud.models.message import Message
from agent_cloud.models.session import Session
from agent_cloud.models.user import User
from agent_cloud.repositories.agent_config import AgentConfigRepository
from agent_cloud.repositories.context_document import ContextDocumentRepository
from agent_cloud.repositories.memory_entry import MemoryEntryRepository
from agent_cloud.repositories.message import MessageRepository
from agent_cloud.repositories.session import SessionRepository
from agent_cloud.repositories.user import UserRepository


async def _make_user(session) -> User:
    user = await UserRepository(session).create(User(email="u@example.com"))
    await session.flush()
    return user


async def _make_agent(session, user) -> AgentConfig:
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, name="a", model="claude-x", provider="anthropic")
    )
    await session.flush()
    return agent


async def test_agent_list_by_user(session):
    user = await _make_user(session)
    await _make_agent(session, user)
    await session.commit()
    agents = await AgentConfigRepository(session).list_by_user(user.id)
    assert len(agents) == 1 and agents[0].user_id == user.id


async def test_session_default_work_subdir(session):
    user = await _make_user(session)
    agent = await _make_agent(session, user)
    repo = SessionRepository(session)
    s = await repo.create_for(user_id=user.id, agent_config_id=agent.id, title="t")
    await session.commit()
    assert s.work_subdir == f"sessions/{s.id}"
    assert s.status == "idle"


async def test_message_seq_autoincrements(session):
    user = await _make_user(session)
    agent = await _make_agent(session, user)
    s = await SessionRepository(session).create_for(user.id, agent.id, None)
    await session.flush()
    repo = MessageRepository(session)
    m0 = await repo.append(s.id, Message(session_id=s.id, seq=0, role="user", content={"text": "hi"}))
    m1 = await repo.append(s.id, Message(session_id=s.id, seq=0, role="assistant", content={"text": "yo"}))
    await session.commit()
    assert m0.seq == 0 and m1.seq == 1
    listed = await repo.list_by_session(s.id)
    assert [m.seq for m in listed] == [0, 1]


async def test_context_document_upsert(session):
    user = await _make_user(session)
    repo = ContextDocumentRepository(session)
    d1 = await repo.upsert(scope="user", type="USER", owner_id=user.id, content="v1")
    await session.commit()
    d2 = await repo.upsert(scope="user", type="USER", owner_id=user.id, content="v2")
    await session.commit()
    assert d1.id == d2.id and d2.content == "v2"  # 同 (scope,type,owner) 覆盖


async def test_memory_append_and_list(session):
    user = await _make_user(session)
    repo = MemoryEntryRepository(session)
    await repo.append(scope="user", owner_id=user.id, content="fact1")
    await repo.append(scope="user", owner_id=user.id, content="fact2")
    await session.commit()
    entries = await repo.list_for_context(scope="user", owner_id=user.id, limit=10)
    assert {e.content for e in entries} == {"fact1", "fact2"}
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/test_repo_entities.py -v`
Expected: FAIL(仓库模块不存在)。

- [ ] **Step 3: AgentConfigRepository**

Create `src/agent_cloud/repositories/agent_config.py`:
```python
import uuid

from sqlalchemy import select

from agent_cloud.models.agent_config import AgentConfig
from agent_cloud.repositories.base import BaseRepository


class AgentConfigRepository(BaseRepository[AgentConfig]):
    model = AgentConfig

    async def list_by_user(self, user_id: uuid.UUID) -> list[AgentConfig]:
        result = await self.session.execute(
            select(AgentConfig).where(AgentConfig.user_id == user_id)
        )
        return list(result.scalars().all())
```

- [ ] **Step 4: SessionRepository(创建时生成 work_subdir)**

Create `src/agent_cloud/repositories/session.py`:
```python
import uuid

from sqlalchemy import select

from agent_cloud.models.session import Session
from agent_cloud.repositories.base import BaseRepository


class SessionRepository(BaseRepository[Session]):
    model = Session

    async def create_for(
        self, user_id: uuid.UUID, agent_config_id: uuid.UUID, title: str | None
    ) -> Session:
        s = Session(
            id=uuid.uuid4(),
            user_id=user_id,
            agent_config_id=agent_config_id,
            title=title,
            work_subdir="",  # 占位,下一行用 id 填充
        )
        s.work_subdir = f"sessions/{s.id}"
        self.session.add(s)
        await self.session.flush()
        return s

    async def list_by_user(self, user_id: uuid.UUID) -> list[Session]:
        result = await self.session.execute(
            select(Session).where(Session.user_id == user_id)
        )
        return list(result.scalars().all())
```

- [ ] **Step 5: MessageRepository(append 自增 seq)**

Create `src/agent_cloud/repositories/message.py`:
```python
import uuid

from sqlalchemy import func, select

from agent_cloud.models.message import Message
from agent_cloud.repositories.base import BaseRepository


class MessageRepository(BaseRepository[Message]):
    model = Message

    async def _next_seq(self, session_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.max(Message.seq), -1)).where(
                Message.session_id == session_id
            )
        )
        return int(result.scalar_one()) + 1

    async def append(self, session_id: uuid.UUID, message: Message) -> Message:
        message.seq = await self._next_seq(session_id)
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_by_session(self, session_id: uuid.UUID) -> list[Message]:
        result = await self.session.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.seq)
        )
        return list(result.scalars().all())
```

- [ ] **Step 6: ContextDocumentRepository(upsert)**

Create `src/agent_cloud/repositories/context_document.py`:
```python
import uuid

from sqlalchemy import select

from agent_cloud.models.context_document import ContextDocument
from agent_cloud.repositories.base import BaseRepository


class ContextDocumentRepository(BaseRepository[ContextDocument]):
    model = ContextDocument

    async def upsert(
        self, scope: str, type: str, owner_id: uuid.UUID, content: str
    ) -> ContextDocument:
        result = await self.session.execute(
            select(ContextDocument).where(
                ContextDocument.scope == scope,
                ContextDocument.type == type,
                ContextDocument.owner_id == owner_id,
            )
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            doc = ContextDocument(scope=scope, type=type, owner_id=owner_id, content=content)
            self.session.add(doc)
        else:
            doc.content = content
        await self.session.flush()
        return doc

    async def list_for_owner(self, scope: str, owner_id: uuid.UUID) -> list[ContextDocument]:
        result = await self.session.execute(
            select(ContextDocument).where(
                ContextDocument.scope == scope, ContextDocument.owner_id == owner_id
            )
        )
        return list(result.scalars().all())
```

- [ ] **Step 7: MemoryEntryRepository(append + list_for_context 接缝)**

Create `src/agent_cloud/repositories/memory_entry.py`:
```python
import uuid

from sqlalchemy import select

from agent_cloud.models.memory_entry import MemoryEntry
from agent_cloud.repositories.base import BaseRepository


class MemoryEntryRepository(BaseRepository[MemoryEntry]):
    model = MemoryEntry

    async def append(
        self, scope: str, owner_id: uuid.UUID, content: str,
        source_session_id: uuid.UUID | None = None,
    ) -> MemoryEntry:
        entry = MemoryEntry(
            scope=scope, owner_id=owner_id, content=content,
            source_session_id=source_session_id,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_for_context(
        self, scope: str, owner_id: uuid.UUID, limit: int = 50
    ) -> list[MemoryEntry]:
        # v1:取最近 N 条。未来引入向量检索时,这里改为 top-k(接口不变)。
        result = await self.session.execute(
            select(MemoryEntry)
            .where(MemoryEntry.scope == scope, MemoryEntry.owner_id == owner_id)
            .order_by(MemoryEntry.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
```

- [ ] **Step 8: 运行,确认通过**

Run: `uv run pytest tests/test_repo_entities.py -v`
Expected: PASS(5 passed)。

- [ ] **Step 9: 提交**

```bash
git add src/agent_cloud/repositories tests/test_repo_entities.py
git commit -m "feat: add repositories for agent configs, sessions, messages, docs, memory"
```

---

### Task 8: API 路由(CRUD)

**Files:**
- Modify: `src/agent_cloud/api/deps.py`
- Create: `src/agent_cloud/api/{users,agent_configs,sessions,context_documents,memory_entries,messages}.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: 写 API 失败测试(端到端,经 HTTP + 真库)**

Create `tests/test_api.py`:
```python
async def test_user_crud(client):
    r = await client.post("/users", json={"email": "x@example.com"})
    assert r.status_code == 201, r.text
    user = r.json()
    uid = user["id"]

    r = await client.get(f"/users/{uid}")
    assert r.status_code == 200 and r.json()["email"] == "x@example.com"


async def test_agent_config_crud(client):
    uid = (await client.post("/users", json={"email": "a@example.com"})).json()["id"]
    r = await client.post(
        "/agent-configs",
        json={"user_id": uid, "name": "coder", "model": "claude-x", "provider": "anthropic"},
    )
    assert r.status_code == 201, r.text
    aid = r.json()["id"]

    r = await client.patch(f"/agent-configs/{aid}", json={"name": "coder2"})
    assert r.status_code == 200 and r.json()["name"] == "coder2"

    r = await client.get(f"/agent-configs?user_id={uid}")
    assert r.status_code == 200 and len(r.json()) == 1


async def test_session_and_messages(client):
    uid = (await client.post("/users", json={"email": "s@example.com"})).json()["id"]
    aid = (
        await client.post(
            "/agent-configs",
            json={"user_id": uid, "name": "c", "model": "m", "provider": "p"},
        )
    ).json()["id"]
    r = await client.post("/sessions", json={"user_id": uid, "agent_config_id": aid})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["work_subdir"] == f"sessions/{sid}"

    r = await client.post(
        f"/sessions/{sid}/messages",
        json={"role": "user", "content": {"text": "hello"}},
    )
    assert r.status_code == 201 and r.json()["seq"] == 0

    r = await client.get(f"/sessions/{sid}/messages")
    assert r.status_code == 200 and len(r.json()) == 1


async def test_context_documents_and_memory(client):
    uid = (await client.post("/users", json={"email": "d@example.com"})).json()["id"]
    r = await client.put(
        "/context-documents",
        json={"scope": "user", "type": "USER", "owner_id": uid, "content": "# me"},
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        "/memory",
        json={"scope": "user", "owner_id": uid, "content": "likes tea"},
    )
    assert r.status_code == 201
    r = await client.get(f"/memory?scope=user&owner_id={uid}")
    assert r.status_code == 200 and r.json()[0]["content"] == "likes tea"
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL(路由 404 / app 未挂载路由)。

- [ ] **Step 3: deps(已存在,确认转发 get_session)**

确认 `src/agent_cloud/api/deps.py` 内容为:
```python
from agent_cloud.db import get_session

__all__ = ["get_session"]
```

- [ ] **Step 4: users 路由**

Create `src/agent_cloud/api/users.py`:
```python
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud.api.deps import get_session
from agent_cloud.models.user import User
from agent_cloud.repositories.user import UserRepository
from agent_cloud.schemas.user import UserCreate, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, session: AsyncSession = Depends(get_session)):
    repo = UserRepository(session)
    user = await repo.create(User(email=body.email))
    await session.commit()
    return user


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    user = await UserRepository(session).get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user
```

- [ ] **Step 5: agent_configs 路由**

Create `src/agent_cloud/api/agent_configs.py`:
```python
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud.api.deps import get_session
from agent_cloud.models.agent_config import AgentConfig
from agent_cloud.repositories.agent_config import AgentConfigRepository
from agent_cloud.schemas.agent_config import (
    AgentConfigCreate,
    AgentConfigRead,
    AgentConfigUpdate,
)

router = APIRouter(prefix="/agent-configs", tags=["agent-configs"])


@router.post("", response_model=AgentConfigRead, status_code=status.HTTP_201_CREATED)
async def create_agent_config(
    body: AgentConfigCreate, session: AsyncSession = Depends(get_session)
):
    repo = AgentConfigRepository(session)
    agent = await repo.create(AgentConfig(**body.model_dump()))
    await session.commit()
    return agent


@router.get("", response_model=list[AgentConfigRead])
async def list_agent_configs(
    user_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    return await AgentConfigRepository(session).list_by_user(user_id)


@router.patch("/{agent_id}", response_model=AgentConfigRead)
async def update_agent_config(
    agent_id: uuid.UUID,
    body: AgentConfigUpdate,
    session: AsyncSession = Depends(get_session),
):
    repo = AgentConfigRepository(session)
    agent = await repo.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent config not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    await session.commit()
    return agent
```

- [ ] **Step 6: sessions + messages 路由**

Create `src/agent_cloud/api/sessions.py`:
```python
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud.api.deps import get_session
from agent_cloud.repositories.session import SessionRepository
from agent_cloud.schemas.session import SessionCreate, SessionRead

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(body: SessionCreate, session: AsyncSession = Depends(get_session)):
    repo = SessionRepository(session)
    s = await repo.create_for(body.user_id, body.agent_config_id, body.title)
    await session.commit()
    return s


@router.get("", response_model=list[SessionRead])
async def list_sessions(user_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await SessionRepository(session).list_by_user(user_id)
```

Create `src/agent_cloud/api/messages.py`:
```python
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud.api.deps import get_session
from agent_cloud.models.message import Message
from agent_cloud.repositories.message import MessageRepository
from agent_cloud.schemas.message import MessageCreate, MessageRead

router = APIRouter(prefix="/sessions/{session_id}/messages", tags=["messages"])


@router.post("", response_model=MessageRead, status_code=status.HTTP_201_CREATED)
async def append_message(
    session_id: uuid.UUID,
    body: MessageCreate,
    session: AsyncSession = Depends(get_session),
):
    repo = MessageRepository(session)
    msg = await repo.append(
        session_id,
        Message(session_id=session_id, seq=0, role=body.role,
                content=body.content, model=body.model, tokens=body.tokens),
    )
    await session.commit()
    return msg


@router.get("", response_model=list[MessageRead])
async def list_messages(
    session_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    return await MessageRepository(session).list_by_session(session_id)
```

- [ ] **Step 7: context_documents + memory 路由**

Create `src/agent_cloud/api/context_documents.py`:
```python
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud.api.deps import get_session
from agent_cloud.repositories.context_document import ContextDocumentRepository
from agent_cloud.schemas.context_document import (
    ContextDocumentRead,
    ContextDocumentUpsert,
)

router = APIRouter(prefix="/context-documents", tags=["context-documents"])


@router.put("", response_model=ContextDocumentRead)
async def upsert_document(
    body: ContextDocumentUpsert, session: AsyncSession = Depends(get_session)
):
    repo = ContextDocumentRepository(session)
    doc = await repo.upsert(body.scope, body.type, body.owner_id, body.content)
    await session.commit()
    return doc


@router.get("", response_model=list[ContextDocumentRead])
async def list_documents(
    scope: str, owner_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    return await ContextDocumentRepository(session).list_for_owner(scope, owner_id)
```

Create `src/agent_cloud/api/memory_entries.py`:
```python
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud.api.deps import get_session
from agent_cloud.repositories.memory_entry import MemoryEntryRepository
from agent_cloud.schemas.memory_entry import MemoryAppend, MemoryRead

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
async def append_memory(body: MemoryAppend, session: AsyncSession = Depends(get_session)):
    repo = MemoryEntryRepository(session)
    entry = await repo.append(body.scope, body.owner_id, body.content, body.source_session_id)
    await session.commit()
    return entry


@router.get("", response_model=list[MemoryRead])
async def list_memory(
    scope: str, owner_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    return await MemoryEntryRepository(session).list_for_context(scope, owner_id)
```

- [ ] **Step 8: 在 app 里挂载所有路由**

Replace `src/agent_cloud/main.py`:
```python
from fastapi import FastAPI

from agent_cloud.api import (
    agent_configs,
    context_documents,
    memory_entries,
    messages,
    sessions,
    users,
)


def create_app() -> FastAPI:
    app = FastAPI(title="Agent Cloud Backend")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    for module in (users, agent_configs, sessions, messages, context_documents, memory_entries):
        app.include_router(module.router)

    return app


app = create_app()
```

- [ ] **Step 9: 运行整套测试**

Run: `uv run pytest -v`
Expected: 全部 PASS(health + models + migration + repos + api)。

- [ ] **Step 10: 提交**

```bash
git add src/agent_cloud/api src/agent_cloud/main.py tests/test_api.py
git commit -m "feat: add CRUD API routers for core entities"
```

---

### Task 9: 收尾(lint + 运行说明 + README 片段)

**Files:**
- Create: `README.md`(运行/测试说明)
- Modify: `pyproject.toml`(ruff 配置)

- [ ] **Step 1: 配置 ruff 并修复**

Add to `pyproject.toml`:
```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```
Run: `uv run ruff check --fix . && uv run ruff format .`
Expected: 无剩余错误。

- [ ] **Step 2: 写最简运行说明**

Create `README.md`:
```markdown
# Agent Cloud Backend

无状态 Agent Cloud 的后端服务(Plan 1:数据层 + CRUD 骨架)。

## 开发

```bash
# 起本地 Postgres
docker run -d --name agent-cloud-pg -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=agent_cloud -p 5432:5432 postgres:16

# 迁移
uv run alembic upgrade head

# 起服务
uv run uvicorn agent_cloud.main:app --reload

# 测试(需 Docker:testcontainers 会拉起临时 Postgres)
uv run pytest -v
```
```

- [ ] **Step 3: 运行整套测试确认绿**

Run: `uv run pytest -v`
Expected: 全部 PASS。

- [ ] **Step 4: 提交**

```bash
git add README.md pyproject.toml
git commit -m "chore: add ruff config and dev README"
```

---

## Self-Review(写完后自检结果)

**Spec 覆盖(Plan 1 范围)**:
- 数据模型 §5.1 的 6 个核心实体 → Task 3 全部建模;迁移 → Task 4。✓
- 配置文档存为 DB 行(非文件)→ ContextDocument 模型 + upsert(Task 3/7)。✓
- memory 读取+追加 + 向量检索接缝 → MemoryEntryRepository.append / list_for_context(Task 7)。✓
- 会话 `work_subdir` 默认每会话子目录、`status` 串行锁字段 → Session 模型 + create_for(Task 3/7)。✓
- 测试用真实 Postgres(不 mock 数据库,spec §13)→ testcontainers fixtures(Task 3)。✓
- 明确延后:skills/sandbox 表、embedding 物理列、auth、agent/worker/sandbox(后续 Plan)。

**占位符扫描**:无 TBD/TODO;每步含完整代码或确切命令与预期。`work_subdir` 用 id 填充的两步写法是真实代码,非占位。

**类型/命名一致性**:仓库方法名在测试与实现间一致(`create_for`、`append`、`list_by_session`、`list_by_user`、`upsert`、`list_for_context`、`list_for_owner`、`get_by_email`);schema 字段与 ORM 字段一致;`get_session` 依赖在 `db.py` 定义、`api/deps.py` 转发、`conftest.py` override,三处一致。
