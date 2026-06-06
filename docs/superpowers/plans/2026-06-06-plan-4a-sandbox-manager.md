# Plan 4a: Sandbox 管理器核心 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现每用户 sandbox 的编排核心:`SandboxRegistry`(Postgres,跨副本可见的运营态)、`SandboxProvisioner` 抽象 + `InProcessProvisioner`(起真沙箱服务、每用户持久工作目录)、`SandboxManager`(get-or-spawn + touch + TTL 回收)。隔离实现,集成测试。

**Architecture:** 都放后端 `agent_cloud_backend/sandbox/`。`SandboxRegistry` 是 Plan 1 预留、现在补上的表。`SandboxProvisioner` 是接口(生产用 Docker/k8s impl,后续;本计划提供 `InProcessProvisioner` 起进程内 `agent_cloud_sandbox` aio 服务,**懒导入** sandbox 包——backend 运行时不强依赖它)。`SandboxManager` 用注入的 sessionmaker(可测)+ provisioner:`get_endpoint_for_user` 查注册表命中则 touch 返回,否则 spawn+登记;`reap_idle` 按 TTL 标死并 stop。

**Tech Stack:** Python 3.12+、SQLAlchemy async、grpcio、pytest + testcontainers(真 Postgres)+ pytest-asyncio。`InProcessProvisioner` 起真沙箱(无需 Docker,进程内 aio)。

参考:spec §5.1(SandboxRegistry)、§9(生命周期:预热/暂停/回收)、§3.1(每服务独立——故 provisioner 是接口)。已合并:2b(`agent_cloud_sandbox.server.create_server`)、1(数据层/repo/迁移管线)。

## 范围

**做**:SandboxRegistry 模型+迁移+仓库;Provisioner 接口 + InProcessProvisioner;SandboxManager(get-or-spawn + TTL 回收)。

**不做(Plan 4b)**:后端 turn 端点按用户路由、reaper 周期触发、跨用户 e2e。真实 Docker/k8s provisioner(部署期)。"暂停/恢复"在 v1 等价于 stop+按需重 spawn(每用户工作目录持久);显式 pause 状态后续。

**已知 v1 取舍**:同一用户并发 `get_endpoint_for_user` 可能竞态双 spawn(老的泄漏到 TTL 回收);per-user spawn 锁是后续优化。`InProcessProvisioner` 仅单副本/开发用(进程内沙箱跨副本不可达)——这正是 provisioner 可插拔的原因。

## File Structure

```
services/backend/src/agent_cloud_backend/
  models/sandbox_registry.py          # SandboxRegistry 表
  models/__init__.py                  # 导出 SandboxRegistry
  repositories/sandbox_registry.py    # SandboxRegistryRepository
  sandbox/__init__.py
  sandbox/provisioner.py              # SandboxProvisioner Protocol + SpawnResult
  sandbox/inprocess.py                # InProcessProvisioner(懒导入 agent_cloud_sandbox)
  sandbox/manager.py                  # SandboxManager
  alembic/versions/*                  # add sandbox_registry(autogenerate)
services/backend/tests/
  test_sandbox_registry.py
  test_inprocess_provisioner.py
  test_sandbox_manager.py
```

---

### Task 0: SandboxRegistry 模型 + 迁移 + 仓库

**Files:**
- Create: `services/backend/src/agent_cloud_backend/models/sandbox_registry.py`, `repositories/sandbox_registry.py`
- Modify: `models/__init__.py`
- Generated: `alembic/versions/*_add_sandbox_registry.py`
- Test: `tests/test_sandbox_registry.py`

- [ ] **Step 1: 写模型**

Create `services/backend/src/agent_cloud_backend/models/sandbox_registry.py`:
```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud_backend.models.base import Base, TimestampMixin, uuid_pk


class SandboxRegistry(Base, TimestampMixin):
    __tablename__ = "sandbox_registry"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(default="active", nullable=False)  # active | dead
    endpoint: Mapped[str] = mapped_column(nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 2: 导出**

Edit `services/backend/src/agent_cloud_backend/models/__init__.py`: add `from agent_cloud_backend.models.sandbox_registry import SandboxRegistry` and add `"SandboxRegistry"` to `__all__`.

- [ ] **Step 3: 写仓库失败测试**

Create `services/backend/tests/test_sandbox_registry.py`:
```python
import uuid
from datetime import datetime, timedelta, timezone

from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.sandbox_registry import SandboxRegistryRepository
from agent_cloud_backend.repositories.user import UserRepository


async def _user(session):
    u = await UserRepository(session).create(User(email=f"{uuid.uuid4()}@e.com"))
    await session.flush()
    return u


async def test_register_and_get_active(session):
    u = await _user(session)
    repo = SandboxRegistryRepository(session)
    sid = uuid.uuid4()
    await repo.register(sid, u.id, "localhost:1234")
    await session.commit()
    got = await repo.get_active_for_user(u.id)
    assert got is not None and got.id == sid and got.endpoint == "localhost:1234"


async def test_get_active_none_when_dead(session):
    u = await _user(session)
    repo = SandboxRegistryRepository(session)
    sid = uuid.uuid4()
    await repo.register(sid, u.id, "x")
    await session.commit()
    await repo.mark_dead(sid)
    await session.commit()
    assert await repo.get_active_for_user(u.id) is None


async def test_touch_updates_last_used(session):
    u = await _user(session)
    repo = SandboxRegistryRepository(session)
    sid = uuid.uuid4()
    sb = await repo.register(sid, u.id, "x")
    await session.commit()
    before = sb.last_used_at
    await repo.touch(sid)
    await session.commit()
    await session.refresh(sb)
    assert sb.last_used_at >= before


async def test_list_active_idle_since(session):
    u = await _user(session)
    repo = SandboxRegistryRepository(session)
    sid = uuid.uuid4()
    await repo.register(sid, u.id, "x")
    await session.commit()
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    stale = await repo.list_active_idle_since(future)  # everything is "idle since" a future cutoff
    assert sid in {s.id for s in stale}
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    assert await repo.list_active_idle_since(past) == []
```

- [ ] **Step 4: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_sandbox_registry.py -v`
Expected: FAIL(`ModuleNotFoundError: ...repositories.sandbox_registry`)。

- [ ] **Step 5: 写仓库**

Create `services/backend/src/agent_cloud_backend/repositories/sandbox_registry.py`:
```python
import uuid
from datetime import datetime

from sqlalchemy import func, select, update

from agent_cloud_backend.models.sandbox_registry import SandboxRegistry
from agent_cloud_backend.repositories.base import BaseRepository


class SandboxRegistryRepository(BaseRepository[SandboxRegistry]):
    model = SandboxRegistry

    async def register(
        self, sandbox_id: uuid.UUID, user_id: uuid.UUID, endpoint: str
    ) -> SandboxRegistry:
        sb = SandboxRegistry(id=sandbox_id, user_id=user_id, endpoint=endpoint, status="active")
        self.session.add(sb)
        await self.session.flush()
        return sb

    async def get_active_for_user(self, user_id: uuid.UUID) -> SandboxRegistry | None:
        result = await self.session.execute(
            select(SandboxRegistry)
            .where(SandboxRegistry.user_id == user_id, SandboxRegistry.status == "active")
            .order_by(SandboxRegistry.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def touch(self, sandbox_id: uuid.UUID) -> None:
        await self.session.execute(
            update(SandboxRegistry)
            .where(SandboxRegistry.id == sandbox_id)
            .values(last_used_at=func.now())
        )

    async def mark_dead(self, sandbox_id: uuid.UUID) -> None:
        await self.session.execute(
            update(SandboxRegistry)
            .where(SandboxRegistry.id == sandbox_id)
            .values(status="dead")
        )

    async def list_active_idle_since(self, cutoff: datetime) -> list[SandboxRegistry]:
        result = await self.session.execute(
            select(SandboxRegistry).where(
                SandboxRegistry.status == "active", SandboxRegistry.last_used_at < cutoff
            )
        )
        return list(result.scalars().all())
```

- [ ] **Step 6: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_sandbox_registry.py -v`
Expected: PASS(4 passed)。

- [ ] **Step 7: 生成迁移**

确保本地 Postgres 在跑(如无:`docker run -d --name agent-cloud-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=agent_cloud -p 5432:5432 postgres:16`;已存在则跳过)。
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run alembic revision --autogenerate -m "add sandbox_registry"
```
Expected: 生成迁移含 `create_table("sandbox_registry", ...)`。打开确认。

- [ ] **Step 8: 提交**

```bash
git add services/backend/src/agent_cloud_backend/models/sandbox_registry.py services/backend/src/agent_cloud_backend/models/__init__.py services/backend/src/agent_cloud_backend/repositories/sandbox_registry.py services/backend/tests/test_sandbox_registry.py services/backend/alembic/versions/
git commit -m "feat(backend): add SandboxRegistry model, repo, and migration"
```

---

### Task 1: Provisioner 接口 + InProcessProvisioner

**Files:**
- Create: `services/backend/src/agent_cloud_backend/sandbox/__init__.py`, `sandbox/provisioner.py`, `sandbox/inprocess.py`
- Test: `tests/test_inprocess_provisioner.py`

- [ ] **Step 1: 写失败测试(对真沙箱)**

Create `services/backend/tests/test_inprocess_provisioner.py`:
```python
import uuid

import grpc

from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc
from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner


async def test_spawn_returns_reachable_sandbox(tmp_path):
    prov = InProcessProvisioner(base_root=tmp_path)
    user_id = uuid.uuid4()
    sandbox_id, endpoint = await prov.spawn(user_id)
    try:
        async with grpc.aio.insecure_channel(endpoint) as channel:
            stub = sandbox_pb2_grpc.SandboxStub(channel)
            resp = await stub.ExecTool(sandbox_pb2.ExecToolRequest(
                call_id="c1", tool_name="write_file",
                arguments_json='{"path": "a.txt", "content": "hi"}', work_subdir="s1"))
        assert resp.is_error is False
        # file landed in the per-user base workdir
        assert (tmp_path / str(user_id) / "s1" / "a.txt").read_text() == "hi"
    finally:
        await prov.stop(sandbox_id)


async def test_persistent_workdir_across_respawn(tmp_path):
    prov = InProcessProvisioner(base_root=tmp_path)
    user_id = uuid.uuid4()
    sid1, ep1 = await prov.spawn(user_id)
    async with grpc.aio.insecure_channel(ep1) as ch:
        await sandbox_pb2_grpc.SandboxStub(ch).ExecTool(sandbox_pb2.ExecToolRequest(
            call_id="c1", tool_name="write_file",
            arguments_json='{"path": "keep.txt", "content": "v"}', work_subdir="s1"))
    await prov.stop(sid1)
    # respawn same user -> same base workdir -> file persists
    sid2, ep2 = await prov.spawn(user_id)
    try:
        async with grpc.aio.insecure_channel(ep2) as ch:
            resp = await sandbox_pb2_grpc.SandboxStub(ch).ExecTool(sandbox_pb2.ExecToolRequest(
                call_id="c2", tool_name="read_file",
                arguments_json='{"path": "keep.txt"}', work_subdir="s1"))
        assert resp.content == "v"
    finally:
        await prov.stop(sid2)


async def test_stop_unknown_is_noop(tmp_path):
    prov = InProcessProvisioner(base_root=tmp_path)
    await prov.stop(uuid.uuid4())  # should not raise
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_inprocess_provisioner.py -v`
Expected: FAIL(`ModuleNotFoundError: ...sandbox.inprocess`)。

- [ ] **Step 3: 写 provisioner 接口**

Create empty `services/backend/src/agent_cloud_backend/sandbox/__init__.py`.

Create `services/backend/src/agent_cloud_backend/sandbox/provisioner.py`:
```python
from __future__ import annotations

import uuid
from typing import Protocol


class SandboxProvisioner(Protocol):
    """提供/销毁 sandbox 的抽象。生产用 Docker/k8s 实现;本仓库提供进程内实现。"""

    async def spawn(self, user_id: uuid.UUID) -> tuple[uuid.UUID, str]:
        """起一个 sandbox,返回 (sandbox_id, endpoint)。"""
        ...

    async def stop(self, sandbox_id: uuid.UUID) -> None:
        """停掉一个 sandbox(未知 id 视为 no-op)。"""
        ...
```

- [ ] **Step 4: 写 InProcessProvisioner**

Create `services/backend/src/agent_cloud_backend/sandbox/inprocess.py`:
```python
from __future__ import annotations

import uuid
from pathlib import Path


class InProcessProvisioner:
    """进程内 provisioner:每用户起一个 agent_cloud_sandbox aio 服务,
    每用户一个持久工作目录(durable 卷的本地替身)。仅单副本/开发用。
    懒导入 agent_cloud_sandbox,避免后端运行时强依赖 sandbox 包。
    """

    def __init__(self, base_root: Path) -> None:
        self._base_root = Path(base_root)
        self._servers: dict[uuid.UUID, object] = {}

    async def spawn(self, user_id: uuid.UUID) -> tuple[uuid.UUID, str]:
        from agent_cloud_sandbox.server import create_server

        sandbox_id = uuid.uuid4()
        workdir = self._base_root / str(user_id)
        workdir.mkdir(parents=True, exist_ok=True)
        server, port = await create_server(base_workdir=workdir, host="localhost", port=0)
        self._servers[sandbox_id] = server
        return sandbox_id, f"localhost:{port}"

    async def stop(self, sandbox_id: uuid.UUID) -> None:
        server = self._servers.pop(sandbox_id, None)
        if server is not None:
            await server.stop(None)
```

- [ ] **Step 5: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_inprocess_provisioner.py -v`
Expected: PASS(3 passed)。

- [ ] **Step 6: 提交**

```bash
git add services/backend/src/agent_cloud_backend/sandbox/__init__.py services/backend/src/agent_cloud_backend/sandbox/provisioner.py services/backend/src/agent_cloud_backend/sandbox/inprocess.py services/backend/tests/test_inprocess_provisioner.py
git commit -m "feat(backend): add SandboxProvisioner protocol and InProcessProvisioner"
```

---

### Task 2: SandboxManager

**Files:**
- Create: `services/backend/src/agent_cloud_backend/sandbox/manager.py`
- Test: `tests/test_sandbox_manager.py`

- [ ] **Step 1: 写失败测试(FakeProvisioner 间谍 + 真注册表)**

Create `services/backend/tests/test_sandbox_manager.py`:
```python
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from agent_cloud_backend.models.sandbox_registry import SandboxRegistry
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.sandbox_registry import SandboxRegistryRepository
from agent_cloud_backend.repositories.user import UserRepository
from agent_cloud_backend.sandbox.manager import SandboxManager


class FakeProvisioner:
    def __init__(self):
        self.spawned: list[uuid.UUID] = []
        self.stopped: list[uuid.UUID] = []

    async def spawn(self, user_id):
        sandbox_id = uuid.uuid4()
        self.spawned.append(sandbox_id)
        return sandbox_id, f"fake:{len(self.spawned)}"

    async def stop(self, sandbox_id):
        self.stopped.append(sandbox_id)


async def _user(engine) -> uuid.UUID:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        u = await UserRepository(s).create(User(email=f"{uuid.uuid4()}@e.com"))
        await s.commit()
        return u.id


async def test_get_endpoint_spawns_then_reuses(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    prov = FakeProvisioner()
    mgr = SandboxManager(provisioner=prov, sessionmaker=maker)
    uid = await _user(engine)

    ep1 = await mgr.get_endpoint_for_user(uid)
    ep2 = await mgr.get_endpoint_for_user(uid)
    assert ep1 == ep2
    assert len(prov.spawned) == 1  # second call reused the registry entry, no new spawn


async def test_reap_idle_marks_dead_and_stops(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    prov = FakeProvisioner()
    mgr = SandboxManager(provisioner=prov, sessionmaker=maker, idle_ttl_seconds=1)
    uid = await _user(engine)
    await mgr.get_endpoint_for_user(uid)

    # force last_used_at far in the past
    async with maker() as s:
        await s.execute(update(SandboxRegistry).values(
            last_used_at=datetime.now(timezone.utc) - timedelta(hours=1)))
        await s.commit()

    reaped = await mgr.reap_idle()
    assert reaped == 1
    assert len(prov.stopped) == 1
    # a new get spawns a fresh one (old is dead)
    await mgr.get_endpoint_for_user(uid)
    assert len(prov.spawned) == 2
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_sandbox_manager.py -v`
Expected: FAIL(`ModuleNotFoundError: ...sandbox.manager`)。

- [ ] **Step 3: 写 manager**

Create `services/backend/src/agent_cloud_backend/sandbox/manager.py`:
```python
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker

from agent_cloud_backend.repositories.sandbox_registry import SandboxRegistryRepository
from agent_cloud_backend.sandbox.provisioner import SandboxProvisioner


class SandboxManager:
    def __init__(
        self,
        provisioner: SandboxProvisioner,
        sessionmaker: async_sessionmaker,
        idle_ttl_seconds: int = 1800,
    ) -> None:
        self._provisioner = provisioner
        self._sessionmaker = sessionmaker
        self._idle_ttl_seconds = idle_ttl_seconds

    async def get_endpoint_for_user(self, user_id: uuid.UUID) -> str:
        async with self._sessionmaker() as db:
            repo = SandboxRegistryRepository(db)
            existing = await repo.get_active_for_user(user_id)
            if existing is not None:
                await repo.touch(existing.id)
                await db.commit()
                return existing.endpoint

        # spawn outside the DB transaction (provisioning may be slow)
        sandbox_id, endpoint = await self._provisioner.spawn(user_id)
        async with self._sessionmaker() as db:
            repo = SandboxRegistryRepository(db)
            await repo.register(sandbox_id, user_id, endpoint)
            await db.commit()
        return endpoint

    async def reap_idle(self) -> int:
        """标记并停掉空闲超 TTL 的 sandbox。返回回收数量。"""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self._idle_ttl_seconds)
        async with self._sessionmaker() as db:
            repo = SandboxRegistryRepository(db)
            stale = await repo.list_active_idle_since(cutoff)
            stale_ids = [s.id for s in stale]
            for sandbox_id in stale_ids:
                await repo.mark_dead(sandbox_id)
            await db.commit()

        for sandbox_id in stale_ids:
            await self._provisioner.stop(sandbox_id)
        return len(stale_ids)
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_sandbox_manager.py -v`
Expected: PASS(2 passed)。

- [ ] **Step 5: 提交**

```bash
git add services/backend/src/agent_cloud_backend/sandbox/manager.py services/backend/tests/test_sandbox_manager.py
git commit -m "feat(backend): add SandboxManager (get-or-spawn + TTL reap)"
```

---

### Task 3: lint + README + 全回归

**Files:**
- Modify: `services/backend/README.md`

- [ ] **Step 1: lint**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run ruff check --fix . && uv run ruff format .`
Expected: clean。

- [ ] **Step 2: README 追加**

在 `services/backend/README.md` 末尾追加:
```markdown

## Sandbox 管理(Plan 4a)
- `SandboxManager.get_endpoint_for_user(user_id)` — 查 `SandboxRegistry`,命中则复用,否则经 `SandboxProvisioner` 起新 sandbox 并登记。`reap_idle()` 按 TTL 回收空闲 sandbox。
- `SandboxProvisioner` 是接口;`InProcessProvisioner`(每用户持久工作目录的进程内实现)仅单副本/开发用,生产用 Docker/k8s impl。
- 后端 turn 端点按用户路由(用 manager 取 endpoint)见 Plan 4b。
```

- [ ] **Step 3: 全回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/packages/common && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest -q
```
Expected:common 9;sandbox 23;worker 49;backend 64(55 + registry 4 + provisioner 3 + manager 2)。

- [ ] **Step 4: 提交**

```bash
git add services/backend/README.md
git commit -m "docs(backend): document sandbox manager"
```

---

## Self-Review(写完后自检结果)

**Spec 覆盖(Plan 4a 范围)**:
- §5.1 SandboxRegistry(运营态,可重建)→ 模型 + 仓库 + 迁移。✓
- §9 生命周期:get-or-spawn(预热的简化:按需起)+ TTL 回收 → `SandboxManager`;每用户持久工作目录(durable 卷替身)→ `InProcessProvisioner`(respawn 保留文件,测试覆盖)。✓
- §3.1 每服务独立:provisioner 是接口,InProcessProvisioner 懒导入 sandbox(后端运行时不强依赖);生产 Docker/k8s impl 后续。✓
- 明确延后:后端按用户路由 + reaper 触发 + 跨用户 e2e(4b)、真实 provisioner、显式 pause 状态、per-user spawn 锁。

**占位符扫描**:无 TBD;每步完整代码或确切命令/预期。

**类型/命名一致性**:`SandboxRegistryRepository.register/get_active_for_user/touch/mark_dead/list_active_idle_since` 在测试与实现一致;`SandboxProvisioner.spawn(user_id)->(sandbox_id,endpoint)` / `stop(sandbox_id)`,`InProcessProvisioner` 与 `FakeProvisioner` 同签名;`SandboxManager(provisioner, sessionmaker, idle_ttl_seconds=1800)`,`get_endpoint_for_user`/`reap_idle` 与测试一致;`SandboxManager` 注入 sessionmaker(可测,优于全局);复用 1 的 `BaseRepository`/迁移管线、2b 的 `create_server`/沙箱桩。
```
