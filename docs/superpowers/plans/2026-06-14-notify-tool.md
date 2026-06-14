# notify 工具(OS 通知 + 应用内 toast)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** agent 调 `notify(title, body)` → 用户在浏览器收到 OS 系统通知 + 应用内 toast(对话中与定时任务运行中都可触发)。

**Architecture:** agent 工具走既有 remember 模式(worker 合成确认 + backend 落库后处理扫 `new_messages`)→ 新 `notifications` 表;前端全局 `NotificationListener`(挂 App)react-query 轮询未送达通知 → `new Notification()`(OS)+ 应用内 toast → mark-delivered。仅"标签页开着时"送达,不引 Web Push。

**Tech Stack:** FastAPI + SQLAlchemy(async)+ Alembic + Postgres;gRPC(worker);React19 + Vite + zustand + react-query;Web Notifications API;pytest + testcontainers;vitest + testing-library。

**Spec:** `docs/superpowers/specs/2026-06-14-notify-tool-design.md`

## Shared Interface Contract

**模型 `Notification`**(`models/notification.py`,表 `notifications`):`id`(uuid pk)/ `user_id`(FK users CASCADE, index)/ `title`(Text)/ `body`(Text)/ `origin_session_id`(uuid FK sessions SET NULL, nullable)/ `delivered_at`(timestamptz nullable)/ `created_at`(TimestampMixin)。索引 `ix_notifications_undelivered`:`(user_id, created_at)` partial `WHERE delivered_at IS NULL`。迁移 down_revision = `b1c2d3e4f5a6`。

**`NotificationRepository(BaseRepository[Notification])`**:`list_undelivered(user_id) -> list[Notification]`、`mark_delivered(ids, user_id) -> None`。

**worker `notify.py`**:`NOTIFY_SPEC`、`notify_enabled(enabled_tools) -> bool`、`class NotifyingExecutor`(仿 `RememberingExecutor`;**不**按 is_scheduled_run 关闭)。

**backend `turn/notify_apply.py`**:`apply_notify_calls(session_id, new_messages) -> int`(仿 `apply_schedule_task_calls`,无自排期护栏)。挂进 `turn/post_persist.py:run_tool_side_effects`。

**schemas `schemas/notification.py`**:`NotificationRead`(from_attributes)、`MarkDeliveredRequest(ids: list[uuid.UUID])`。**API**:`GET /notifications`、`POST /notifications/mark-delivered`。

**前端**:`types.ts` `Notification`;`api/client.ts` `listNotifications`/`markNotificationsDelivered`;`agentConfig.ts` `BUILTIN_TOOLS` 加 `notify`;`components/NotificationListener.tsx`(挂 `App`)。

## 测试约定

后端 `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" <path> -v`(DB 测试用 `session`/`auth_client`/`migration_pg_url`;走全局 `get_sessionmaker` 的代码由 `engine` fixture 自动指到测试库)。worker `cd services/worker && uv run pytest <path> -v`。前端 `cd frontend && npm run lint` + `npx vitest run <path>`。所有 Write/Edit 用 worktree 前缀 `/Users/wuhaowen/src/llm-agent/agent-cloud/.claude/worktrees/notify-tool/`。

---

## Phase 1 — 数据层

### Task 1: `Notification` 模型 + 注册 + 迁移

**Files:**
- Create: `services/backend/src/agent_cloud_backend/models/notification.py`
- Modify: `services/backend/src/agent_cloud_backend/models/__init__.py`(import + `__all__`)
- Create: `services/backend/alembic/versions/c2d3e4f5a6b7_notifications.py`
- Test: `services/backend/tests/test_notification_model.py`、`services/backend/tests/test_migration.py`(加一例)

- [ ] **Step 1: 写失败测试** `tests/test_notification_model.py`

```python
import uuid

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.notification import Notification
from agent_cloud_backend.models.user import User


async def test_notification_row_roundtrip(session):
    u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
    session.add(u)
    await session.flush()
    n = Notification(user_id=u.id, title="喝药提醒", body="该喝药了")
    session.add(n)
    await session.commit()
    got = await session.get(Notification, n.id)
    assert got.title == "喝药提醒"
    assert got.delivered_at is None
    assert got.origin_session_id is None
    assert got.created_at is not None
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_notification_model.py -v`
Expected: FAIL(`ImportError: cannot import name 'Notification'`)

- [ ] **Step 3: 建模型** `models/notification.py`

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud_backend.models.base import Base, TimestampMixin, uuid_pk


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    origin_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ix_notifications_undelivered",
            "user_id",
            "created_at",
            postgresql_where=text("delivered_at IS NULL"),
        ),
    )
```

- [ ] **Step 4: 注册 metadata** —— `models/__init__.py` 加 `from agent_cloud_backend.models.notification import Notification`(放在 memory_entry 与 provider_credential 之间,字母序)并把 `"Notification"` 加入 `__all__`。

- [ ] **Step 5: 跑确认 model 测试 pass**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_notification_model.py -v`
Expected: PASS

- [ ] **Step 6: 写迁移失败测试** —— `tests/test_migration.py` 末尾追加:

```python
def test_notifications_schema(migration_pg_url: str):
    import os

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    sync_url = migration_pg_url.replace("+asyncpg", "")
    os.environ["AGENT_CLOUD_DATABASE_URL"] = migration_pg_url
    command.upgrade(Config("alembic.ini"), "head")

    engine = create_engine(sync_url)
    with engine.connect() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            )
        }
        idx = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE schemaname='public' "
                    "AND tablename='notifications'"
                )
            )
        }
    assert "notifications" in tables
    assert "ix_notifications_undelivered" in idx
```

- [ ] **Step 7: 跑确认 fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_migration.py::test_notifications_schema -v`
Expected: FAIL(`notifications` 不在 tables)

- [ ] **Step 8: 写迁移** `services/backend/alembic/versions/c2d3e4f5a6b7_notifications.py`

```python
"""notifications

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-06-14
"""

import sqlalchemy as sa
from alembic import op

revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "origin_session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index(
        "ix_notifications_undelivered",
        "notifications",
        ["user_id", "created_at"],
        postgresql_where=sa.text("delivered_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_undelivered", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
```

- [ ] **Step 9: 跑确认 migration pass + commit**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_migration.py -v`
Expected: PASS(既有 + 新 `test_notifications_schema` 全过)
```bash
git add services/backend/src/agent_cloud_backend/models/notification.py services/backend/src/agent_cloud_backend/models/__init__.py services/backend/alembic/versions/c2d3e4f5a6b7_notifications.py services/backend/tests/test_notification_model.py services/backend/tests/test_migration.py
git commit -m "feat(notify): Notification model + migration"
```

---

### Task 2: `NotificationRepository`

**Files:**
- Create: `services/backend/src/agent_cloud_backend/repositories/notification.py`
- Test: `services/backend/tests/test_notification_repo.py`

- [ ] **Step 1: 写失败测试** `tests/test_notification_repo.py`

```python
import uuid

from agent_cloud_backend.models.notification import Notification
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.notification import NotificationRepository


async def _user(session) -> uuid.UUID:
    u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
    session.add(u)
    await session.flush()
    return u.id


async def test_list_undelivered_scopes_and_excludes_delivered(session):
    uid = await _user(session)
    other = await _user(session)
    session.add(Notification(user_id=uid, title="a", body="x"))
    session.add(Notification(user_id=other, title="b", body="x"))
    await session.commit()
    repo = NotificationRepository(session)
    rows = await repo.list_undelivered(uid)
    assert [r.title for r in rows] == ["a"]


async def test_mark_delivered(session):
    uid = await _user(session)
    n = Notification(user_id=uid, title="a", body="x")
    session.add(n)
    await session.commit()
    repo = NotificationRepository(session)
    await repo.mark_delivered([n.id], uid)
    await session.commit()
    assert await repo.list_undelivered(uid) == []


async def test_mark_delivered_scoped_to_owner(session):
    uid = await _user(session)
    other = await _user(session)
    n = Notification(user_id=uid, title="a", body="x")
    session.add(n)
    await session.commit()
    repo = NotificationRepository(session)
    await repo.mark_delivered([n.id], other)  # 非属主 → 不动
    await session.commit()
    assert len(await repo.list_undelivered(uid)) == 1
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_notification_repo.py -v`
Expected: FAIL(`ImportError: NotificationRepository`)

- [ ] **Step 3: 建仓库** `repositories/notification.py`

```python
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from agent_cloud_backend.models.notification import Notification
from agent_cloud_backend.repositories.base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    model = Notification

    async def list_undelivered(self, user_id: uuid.UUID) -> list[Notification]:
        result = await self.session.execute(
            select(Notification)
            .where(Notification.user_id == user_id, Notification.delivered_at.is_(None))
            .order_by(Notification.created_at)
        )
        return list(result.scalars().all())

    async def mark_delivered(self, ids: list[uuid.UUID], user_id: uuid.UUID) -> None:
        """把这些(且属本人)通知置已送达。幂等。空 ids 直接返回。"""
        if not ids:
            return
        await self.session.execute(
            update(Notification)
            .where(Notification.id.in_(ids), Notification.user_id == user_id)
            .values(delivered_at=datetime.now(UTC))
        )
```

- [ ] **Step 4: 跑确认 pass + commit**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_notification_repo.py -v`
Expected: PASS(3 passed)
```bash
git add services/backend/src/agent_cloud_backend/repositories/notification.py services/backend/tests/test_notification_repo.py
git commit -m "feat(notify): NotificationRepository (list_undelivered / mark_delivered)"
```

---

## Phase 2 — agent 工具 + 落库

### Task 3: worker `notify` 工具(`NotifyingExecutor`)

**Files:**
- Create: `services/worker/src/agent_cloud_worker/notify.py`
- Modify: `services/worker/src/agent_cloud_worker/server.py`(`_build_executor` 包一层 + import)
- Test: `services/worker/tests/test_notify.py`

- [ ] **Step 1: 写失败测试** `services/worker/tests/test_notify.py`

```python
from agent_cloud_common import ToolCall, ToolResult, ToolSpec
from agent_cloud_worker.notify import NOTIFY_SPEC, NotifyingExecutor, notify_enabled


class _Inner:
    def specs(self):
        return [ToolSpec(name="bash", description="", input_schema={})]

    async def execute(self, call):
        return ToolResult(call_id=call.id, content=f"ran {call.name}", is_error=False)


def test_enabled_logic():
    assert notify_enabled([]) is True
    assert notify_enabled(["notify"]) is True
    assert notify_enabled(["bash"]) is False


def test_specs_gated():
    assert "notify" in [s.name for s in NotifyingExecutor(_Inner(), enabled=True).specs()]
    assert "notify" not in [s.name for s in NotifyingExecutor(_Inner(), enabled=False).specs()]


async def test_intercept_returns_confirmation_not_forwarded():
    ex = NotifyingExecutor(_Inner(), enabled=True)
    r = await ex.execute(ToolCall(id="1", name="notify", arguments={"title": "嗨", "body": "该喝药了"}))
    assert r.is_error is False
    assert "ran notify" not in r.content


async def test_non_notify_delegates():
    ex = NotifyingExecutor(_Inner(), enabled=True)
    r = await ex.execute(ToolCall(id="2", name="bash", arguments={"command": "ls"}))
    assert r.content == "ran bash"


async def test_validates_required_fields():
    ex = NotifyingExecutor(_Inner(), enabled=True)
    r = await ex.execute(ToolCall(id="1", name="notify", arguments={"title": "嗨"}))
    assert r.is_error


async def test_disabled_rejects():
    ex = NotifyingExecutor(_Inner(), enabled=False)
    r = await ex.execute(ToolCall(id="1", name="notify", arguments={"title": "a", "body": "b"}))
    assert r.is_error is True


def test_spec_required_fields():
    assert set(NOTIFY_SPEC.input_schema["required"]) == {"title", "body"}
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd services/worker && uv run pytest tests/test_notify.py -v`
Expected: FAIL(`ModuleNotFoundError: notify`)

- [ ] **Step 3: 实现** `services/worker/src/agent_cloud_worker/notify.py`

```python
from __future__ import annotations

from agent_cloud_common import ToolCall, ToolResult, ToolSpec

from agent_cloud_worker.tools import ToolExecutor

# 提醒用户工具(worker 原生:本地校验 + 合成确认,不碰 DB、不转沙箱)。tool_call/result 随
# new_messages 回 backend,落库后处理 apply_notify_calls 扫到并 INSERT notifications;前端轮询
# 拉取后弹 OS 通知 + 应用内 toast(spec 2026-06-14-notify-tool)。定时任务运行里也可调(主用例)。
NOTIFY_SPEC = ToolSpec(
    name="notify",
    description=(
        "Notify the user with an OS notification + in-app popup. Use to actively alert the user "
        "(e.g. a scheduled reminder firing, or a heads-up mid-conversation). title is a short "
        "heading; body is the message. Delivered to the user's open browser tab."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short notification heading."},
            "body": {"type": "string", "description": "Notification message body."},
        },
        "required": ["title", "body"],
    },
)


def notify_enabled(enabled_tools: list[str]) -> bool:
    """空 enabled_tools = 全部(含 notify);否则需显式列出。"""
    return not enabled_tools or "notify" in enabled_tools


class NotifyingExecutor:
    """装饰 ToolExecutor:加 worker 原生 ``notify`` 工具。本地校验 + 合成确认,**不碰 DB、不转
    沙箱**;其余委托内层。真正落库由 backend 扫 new_messages 完成(含 enabled_tools 重校验)。
    与 schedule_task 不同:**不**按 is_scheduled_run 关闭——定时任务到点提醒正是主用例。"""

    def __init__(self, inner: ToolExecutor, *, enabled: bool) -> None:
        self._inner = inner
        self._enabled = enabled

    def specs(self) -> list[ToolSpec]:
        specs = list(self._inner.specs())
        if self._enabled:
            specs.append(NOTIFY_SPEC)
        return specs

    async def execute(self, call: ToolCall) -> ToolResult:
        if call.name != "notify":
            return await self._inner.execute(call)
        if not self._enabled:
            return ToolResult(call_id=call.id, content="tool not enabled: notify", is_error=True)
        args = call.arguments or {}
        title = args.get("title")
        body = args.get("body")
        if not all(isinstance(x, str) and x.strip() for x in (title, body)):
            return ToolResult(
                call_id=call.id, content="notify: title and body are required", is_error=True
            )
        return ToolResult(call_id=call.id, content=f"Notified user: {title}", is_error=False)
```

- [ ] **Step 4: 接进 `_build_executor`** —— `services/worker/src/agent_cloud_worker/server.py`:import 处加
```python
from agent_cloud_worker.notify import NotifyingExecutor, notify_enabled
```
在 `executor = RememberingExecutor(sandbox_exec, enabled=remember_enabled(enabled_tools))` 之后加:
```python
        executor = NotifyingExecutor(executor, enabled=notify_enabled(enabled_tools))
```

- [ ] **Step 5: 跑确认 pass + worker 整体不回归 + commit**

Run: `cd services/worker && uv run pytest tests/test_notify.py -v`
Expected: PASS(7 passed)
Run: `cd services/worker && uv run pytest -q`
Expected: 全绿
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/.claude/worktrees/notify-tool
git add services/worker/src/agent_cloud_worker/notify.py services/worker/src/agent_cloud_worker/server.py services/worker/tests/test_notify.py
git commit -m "feat(notify): worker notify tool (NotifyingExecutor)"
```

---

### Task 4: backend `apply_notify_calls` + 接入 `run_tool_side_effects`

**Files:**
- Create: `services/backend/src/agent_cloud_backend/turn/notify_apply.py`
- Modify: `services/backend/src/agent_cloud_backend/turn/post_persist.py`
- Test: `services/backend/tests/test_notify_apply.py`

- [ ] **Step 1: 写失败测试** `tests/test_notify_apply.py`

```python
import uuid

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.notification import NotificationRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.turn.notify_apply import apply_notify_calls
from agent_cloud_common import Message as CMessage
from agent_cloud_common import Role, ToolCall, ToolResult
from sqlalchemy.ext.asyncio import async_sessionmaker


def _calls(args, *, ok=True, name="notify", cid="c1"):
    a = CMessage(role=Role.ASSISTANT, tool_calls=[ToolCall(id=cid, name=name, arguments=args)])
    t = CMessage(role=Role.TOOL, tool_results=[ToolResult(call_id=cid, content="ok", is_error=not ok)])
    return [a, t]


async def _seed(maker, *, enabled_tools=None):
    async with maker() as s:
        u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
        s.add(u)
        await s.flush()
        a = AgentConfig(user_id=u.id, name="a", model="m", provider="p", enabled_tools=enabled_tools or [])
        s.add(a)
        await s.flush()
        sess = await SessionRepository(s).create_for(u.id, a.id, "c")
        await s.commit()
        return u.id, sess.id


GOOD = {"title": "喝药提醒", "body": "该喝药了"}


async def test_inserts_notification_with_origin(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    uid, sid = await _seed(maker)
    n = await apply_notify_calls(sid, _calls(GOOD))
    assert n == 1
    async with maker() as s:
        rows = await NotificationRepository(s).list_undelivered(uid)
        assert len(rows) == 1
        assert rows[0].title == "喝药提醒"
        assert rows[0].origin_session_id == sid


async def test_skips_error_result(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    _, sid = await _seed(maker)
    assert await apply_notify_calls(sid, _calls(GOOD, ok=False)) == 0


async def test_enforces_enabled_tools(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    _, sid = await _seed(maker, enabled_tools=["bash"])
    assert await apply_notify_calls(sid, _calls(GOOD)) == 0
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_notify_apply.py -v`
Expected: FAIL(`ModuleNotFoundError: turn.notify_apply`)

- [ ] **Step 3: 实现** `services/backend/src/agent_cloud_backend/turn/notify_apply.py`

```python
from __future__ import annotations

import logging
import uuid

from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.notification import Notification
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository

logger = logging.getLogger(__name__)


def _accepted_notify_calls(new_messages) -> list:
    """worker【已接受】(tool_result 非错误)、按 call_id 去重的 notify 调用。"""
    ok_ids = {
        r.call_id
        for m in new_messages
        for r in (getattr(m, "tool_results", None) or [])
        if not r.is_error
    }
    seen: set[str] = set()
    calls = []
    for m in new_messages:
        for c in getattr(m, "tool_calls", None) or []:
            if c.name == "notify" and c.id in ok_ids and c.id not in seen:
                seen.add(c.id)
                calls.append(c)
    return calls


async def apply_notify_calls(session_id: uuid.UUID, new_messages) -> int:
    """把本回合 agent 主动 notify 的调用落成 notifications 行(spec 2026-06-14)。

    独立事务、best-effort。服务端重校验 enabled_tools;user_id/origin 取自服务端会话(不取 LLM)。
    与 schedule_task 不同:**无自排期护栏**——定时运行里 notify 正是主用例。返回新建行数。
    """
    calls = _accepted_notify_calls(new_messages)
    if not calls:
        return 0
    async with get_sessionmaker()() as db:
        s = await db.get(Session, session_id)
        if s is None:
            return 0
        agent = await AgentConfigRepository(db).get(s.agent_config_id)
        enabled = list(agent.enabled_tools) if agent else []
        if enabled and "notify" not in enabled:
            return 0
        created = 0
        for c in calls:
            args = c.arguments or {}
            title, body = args.get("title"), args.get("body")
            if not all(isinstance(x, str) and x.strip() for x in (title, body)):
                continue
            db.add(
                Notification(
                    user_id=s.user_id,
                    title=title.strip(),
                    body=body.strip(),
                    origin_session_id=session_id,
                )
            )
            created += 1
        await db.commit()
        return created
```

- [ ] **Step 4: 接入 `run_tool_side_effects`** —— `turn/post_persist.py`:import 加 `from agent_cloud_backend.turn.notify_apply import apply_notify_calls`;把 `for fn in (apply_remember_calls, apply_schedule_task_calls):` 改为 `for fn in (apply_remember_calls, apply_schedule_task_calls, apply_notify_calls):`。

- [ ] **Step 5: 跑确认 pass + commit**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_notify_apply.py -v`
Expected: PASS(3 passed)
```bash
git add services/backend/src/agent_cloud_backend/turn/notify_apply.py services/backend/src/agent_cloud_backend/turn/post_persist.py services/backend/tests/test_notify_apply.py
git commit -m "feat(notify): apply_notify_calls + wire into run_tool_side_effects"
```

---

## Phase 3 — API

### Task 5: schemas + `GET /notifications` + mark-delivered

**Files:**
- Create: `services/backend/src/agent_cloud_backend/schemas/notification.py`
- Create: `services/backend/src/agent_cloud_backend/api/notifications.py`
- Modify: `services/backend/src/agent_cloud_backend/main.py`(注册 router)
- Test: `services/backend/tests/test_notifications_api.py`

- [ ] **Step 1: 写失败测试** `tests/test_notifications_api.py`

```python
import uuid

from agent_cloud_backend.models.notification import Notification
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.conftest import register_user


async def _seed_notif(engine, user_id: str) -> str:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        n = Notification(user_id=uuid.UUID(user_id), title="喝药提醒", body="该喝药了")
        s.add(n)
        await s.commit()
        return str(n.id)


async def test_list_returns_undelivered(auth_client, engine):
    await _seed_notif(engine, auth_client.user_id)
    r = await auth_client.get("/notifications")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["title"] == "喝药提醒"


async def test_mark_delivered_clears(auth_client, engine):
    nid = await _seed_notif(engine, auth_client.user_id)
    r = await auth_client.post("/notifications/mark-delivered", json={"ids": [nid]})
    assert r.status_code == 204
    assert (await auth_client.get("/notifications")).json() == []


async def test_list_scoped_to_user(auth_client, client, engine):
    await _seed_notif(engine, auth_client.user_id)
    other_access, other_id = await register_user(client)
    await _seed_notif(engine, other_id)
    # 本人只看到自己的那条
    assert len((await auth_client.get("/notifications")).json()) == 1
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_notifications_api.py -v`
Expected: FAIL(404 路由不存在)

- [ ] **Step 3: 建 schemas** `schemas/notification.py`

```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    body: str
    origin_session_id: uuid.UUID | None
    created_at: datetime


class MarkDeliveredRequest(BaseModel):
    ids: list[uuid.UUID]
```

- [ ] **Step 4: 建路由** `api/notifications.py`

```python
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.notification import NotificationRepository
from agent_cloud_backend.schemas.notification import MarkDeliveredRequest, NotificationRead

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
async def list_notifications(
    session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)
):
    return await NotificationRepository(session).list_undelivered(user.id)


@router.post("/mark-delivered", status_code=status.HTTP_204_NO_CONTENT)
async def mark_delivered(
    body: MarkDeliveredRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    await NotificationRepository(session).mark_delivered(body.ids, user.id)
    await session.commit()
```

- [ ] **Step 5: 注册 router** —— `main.py` 的 `from agent_cloud_backend.api import (...)` 加 `notifications`(字母序:messages 后、scheduled_tasks 前),并加进 `for module in (...)` 元组。

- [ ] **Step 6: 跑确认 pass + commit**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_notifications_api.py -v`
Expected: PASS(3 passed)
```bash
git add services/backend/src/agent_cloud_backend/schemas/notification.py services/backend/src/agent_cloud_backend/api/notifications.py services/backend/src/agent_cloud_backend/main.py services/backend/tests/test_notifications_api.py
git commit -m "feat(notify): GET /notifications + mark-delivered"
```

- [ ] **Step 7: Phase 1-3 后端收口回归**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q && uv run ruff check src tests`
Expected: 全绿 + ruff clean

---

## Phase 4 — 前端

### Task 6: types + api client + `notify` 工具开关

**Files:**
- Modify: `frontend/src/types.ts`(加 `Notification`)
- Modify: `frontend/src/api/client.ts`(list/markDelivered)
- Modify: `frontend/src/agentConfig.ts`(`BUILTIN_TOOLS` 加 notify)
- 验证:`npm run lint`(行为测试在 Task 7)

- [ ] **Step 1: `types.ts`** —— 末尾加(注意:前端类型名叫 `Notification`,与 DOM 的 `Notification` 构造器同名但不冲突——一个是 `type`,一个是值;监听器里用 `import type { Notification as AppNotification }` 别名规避):

```ts
export interface Notification {
  id: string
  title: string
  body: string
  origin_session_id: string | null
  created_at: string
}
```

- [ ] **Step 2: `api/client.ts`** —— 顶部 import 的 `from "../types"` 列表加 `Notification`(字母序);`api` 对象里(scheduledTasks 块附近)加:

```ts
  listNotifications: () => http<Notification[]>("/notifications"),
  markNotificationsDelivered: (ids: string[]) =>
    http<void>("/notifications/mark-delivered", { method: "POST", body: JSON.stringify({ ids }) }),
```

- [ ] **Step 3: `agentConfig.ts`** —— `BUILTIN_TOOLS` 加一项(放在 `schedule_task` 后):

```ts
  { name: "notify", desc: "提醒用户(系统通知 + 网页弹窗)" },
```

- [ ] **Step 4: 验证 + commit**

Run: `cd frontend && npm run lint`
Expected: 通过(tsc -b 无错)
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/.claude/worktrees/notify-tool
git add frontend/src/types.ts frontend/src/api/client.ts frontend/src/agentConfig.ts
git commit -m "feat(notify): frontend types + api client + notify tool toggle"
```

---

### Task 7: `NotificationListener`(轮询 + OS 通知 + toast + 权限 banner)

**Files:**
- Create: `frontend/src/components/NotificationListener.tsx`
- Modify: `frontend/src/App.tsx`(挂进已登录树)
- Test: `frontend/src/components/NotificationListener.test.tsx`

- [ ] **Step 1: 写失败测试** `frontend/src/components/NotificationListener.test.tsx`

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { useStore } from "../store"
import type { Notification as AppNotification } from "../types"
import { NotificationListener } from "./NotificationListener"

const notif = (over: Partial<AppNotification> = {}): AppNotification => ({
  id: "n1",
  title: "喝药提醒",
  body: "该喝药了",
  origin_session_id: null,
  created_at: "2026-06-14T08:00:00+00:00",
  ...over,
})

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

beforeEach(() => {
  useStore.setState({ userId: "u1" })
  localStorage.clear()
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("NotificationListener", () => {
  it("轮询到通知 → 弹 toast + 调 markNotificationsDelivered", async () => {
    vi.stubGlobal("Notification", Object.assign(vi.fn(), { permission: "denied" }))
    vi.spyOn(api, "listNotifications").mockResolvedValue([notif()])
    const mark = vi.spyOn(api, "markNotificationsDelivered").mockResolvedValue(undefined)
    render(wrap(<NotificationListener />))
    expect(await screen.findByText("喝药提醒")).toBeInTheDocument()
    expect(screen.getByText("该喝药了")).toBeInTheDocument()
    await waitFor(() => expect(mark).toHaveBeenCalledWith(["n1"]))
  })

  it("已授权 → 构造 OS Notification", async () => {
    const NotifMock = Object.assign(vi.fn(), { permission: "granted" })
    vi.stubGlobal("Notification", NotifMock)
    vi.spyOn(api, "listNotifications").mockResolvedValue([notif()])
    vi.spyOn(api, "markNotificationsDelivered").mockResolvedValue(undefined)
    render(wrap(<NotificationListener />))
    await waitFor(() =>
      expect(NotifMock).toHaveBeenCalledWith("喝药提醒", { body: "该喝药了" }),
    )
  })

  it("permission=default → 显示开启 banner,点击调 requestPermission", async () => {
    const reqPerm = vi.fn().mockResolvedValue("granted")
    vi.stubGlobal(
      "Notification",
      Object.assign(vi.fn(), { permission: "default", requestPermission: reqPerm }),
    )
    vi.spyOn(api, "listNotifications").mockResolvedValue([])
    render(wrap(<NotificationListener />))
    fireEvent.click(await screen.findByRole("button", { name: "开启" }))
    await waitFor(() => expect(reqPerm).toHaveBeenCalled())
  })

  it("不支持 Notification 时只弹 toast,不崩", async () => {
    vi.stubGlobal("Notification", undefined)
    vi.spyOn(api, "listNotifications").mockResolvedValue([notif()])
    vi.spyOn(api, "markNotificationsDelivered").mockResolvedValue(undefined)
    render(wrap(<NotificationListener />))
    expect(await screen.findByText("喝药提醒")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "开启" })).toBeNull()
  })
})
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd frontend && npx vitest run src/components/NotificationListener.test.tsx`
Expected: FAIL(找不到模块 `NotificationListener`)

- [ ] **Step 3: 实现** `frontend/src/components/NotificationListener.tsx`

```tsx
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"
import type { Notification as AppNotification } from "../types"

const PERM_DISMISS_KEY = "ac.notifPermDismissed"

// 安全取 DOM Notification 构造器(jsdom / 老浏览器可能没有 → 优雅降级:只弹应用内 toast)。
function getNotif(): typeof Notification | undefined {
  return typeof window !== "undefined" && "Notification" in window ? window.Notification : undefined
}

// 全局通知监听器(挂 App,已登录树内):轮询未送达通知 → OS 通知 + 应用内 toast → mark-delivered。
// 仅"标签页开着时"送达(spec 2026-06-14)。
export function NotificationListener() {
  const userId = useStore((s) => s.userId)
  const setSession = useStore((s) => s.setSession)
  const qc = useQueryClient()
  const [toasts, setToasts] = useState<AppNotification[]>([])
  const [permDismissed, setPermDismissed] = useState(
    () => localStorage.getItem(PERM_DISMISS_KEY) === "1",
  )
  const seen = useRef<Set<string>>(new Set()) // 防多轮轮询/重渲染重复处理同一条

  const { data: pending = [] } = useQuery({
    queryKey: ["notifications", userId],
    queryFn: () => api.listNotifications(),
    enabled: !!userId,
    refetchInterval: 15000,
  })

  useEffect(() => {
    const fresh = pending.filter((n) => !seen.current.has(n.id))
    if (fresh.length === 0) return
    const N = getNotif()
    for (const n of fresh) {
      seen.current.add(n.id)
      if (N && N.permission === "granted") {
        try {
          new N(n.title, { body: n.body })
        } catch {
          /* 某些上下文构造会抛;忽略,应用内 toast 仍在 */
        }
      }
    }
    setToasts((prev) => [...prev, ...fresh])
    void api
      .markNotificationsDelivered(fresh.map((n) => n.id))
      .then(() => qc.invalidateQueries({ queryKey: ["notifications", userId] }))
  }, [pending, userId, qc])

  const dismiss = (id: string) => setToasts((t) => t.filter((x) => x.id !== id))
  const openOrigin = (n: AppNotification) => {
    if (n.origin_session_id) setSession(n.origin_session_id)
    dismiss(n.id)
  }
  const closeBanner = () => {
    setPermDismissed(true)
    localStorage.setItem(PERM_DISMISS_KEY, "1")
  }
  const askPerm = () => {
    const N = getNotif()
    if (N) void N.requestPermission().finally(closeBanner)
    else closeBanner()
  }

  const N = getNotif()
  const showBanner = !!userId && !!N && N.permission === "default" && !permDismissed

  return (
    <>
      {showBanner && (
        <div className="fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm shadow-pop">
          <span className="text-slate-600">开启系统提醒?定时任务到点会弹通知</span>
          <button
            type="button"
            className="rounded-lg bg-brand-500 px-3 py-1 text-xs font-medium text-white hover:bg-brand-600"
            onClick={askPerm}
          >
            开启
          </button>
          <button
            type="button"
            aria-label="关闭"
            className="text-slate-400 hover:text-slate-600"
            onClick={closeBanner}
          >
            ✕
          </button>
        </div>
      )}
      <div
        className="fixed bottom-4 right-4 z-50 flex flex-col gap-2"
        role="region"
        aria-label="通知"
      >
        {toasts.map((n) => (
          <div
            key={n.id}
            role="alert"
            className="flex w-72 items-start gap-2 rounded-xl border border-slate-200 bg-white p-3 shadow-pop"
          >
            <button
              type="button"
              className="min-w-0 flex-1 text-left"
              onClick={() => openOrigin(n)}
            >
              <div className="truncate text-sm font-medium text-slate-800">{n.title}</div>
              <div className="mt-0.5 text-xs text-slate-500">{n.body}</div>
            </button>
            <button
              type="button"
              aria-label={`关闭 ${n.title}`}
              className="shrink-0 text-slate-400 hover:text-slate-600"
              onClick={() => dismiss(n.id)}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </>
  )
}
```

- [ ] **Step 4: 挂进 `App.tsx`** —— 在已登录返回的 JSX 里(`<div className="flex h-full overflow-hidden">` 内,与 `FileDrawer`/`SettingsDrawer` 并列)加 `<NotificationListener />`;顶部 import `import { NotificationListener } from "./components/NotificationListener"`。

```tsx
      <FileDrawer />
      <SettingsDrawer />
      <NotificationListener />
      {terminalMounted && <TerminalWindow />}
```

- [ ] **Step 5: 跑确认 pass + lint + commit**

Run: `cd frontend && npx vitest run src/components/NotificationListener.test.tsx && npm run lint`
Expected: PASS(4 passed)+ lint 通过
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/.claude/worktrees/notify-tool
git add frontend/src/components/NotificationListener.tsx frontend/src/App.tsx frontend/src/components/NotificationListener.test.tsx
git commit -m "feat(notify): NotificationListener (poll + OS notification + toast + permission)"
```

---

## Phase 5 — 收尾

### Task 8: 全量回归 + 对抗审查 + PR

- [ ] **Step 1: 全量回归**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q && uv run ruff check src tests`(全绿 + clean)
Run: `cd services/worker && uv run pytest -q && uv run ruff check src tests`(全绿 + clean)
Run: `cd frontend && npm run lint && npm test`(tsc + vitest 全绿)

- [ ] **Step 2: 对抗式代码审查**(Opus 4.8 子 agent,diff 内联)。重点:
  - 落库后处理:`apply_notify_calls` 抛错不影响 remember/schedule(各自 best-effort);notify 不被 is_scheduled_run 关闭(定时提醒主用例)。
  - 信任边界:`apply_notify_calls` 的 user_id/origin 取自服务端会话、重校验 enabled_tools。
  - 前端:多标签页重复弹(已知接受);`seen` ref + mark-delivered 防同一条重弹;无 `Notification` 时不崩(降级);`requestPermission` 由用户手势触发;通知正文 React 自动转义(无 XSS)。
  - mark-delivered 幂等 + 归属隔离。
- [ ] **Step 3: 按发现修复(每条一 commit;真 bug 先补失败测试)。修完再跑 Step 1 全量回归。**

- [ ] **Step 4: 完成开发分支(PR)** —— 用 superpowers:finishing-a-development-branch:验证测试 → 选 **Push and create a Pull Request**(走既有 PR 流程,CI 跑全套)。PR 正文含 Summary + 设计/计划链接 + Test Plan。等 CI 绿、按用户节奏合并 + 部署。

---

## 计划自审(writing-plans self-review)

**1. Spec 覆盖**:§4 数据模型 → T1;§5 工具+落库 → T3(worker)+T4(apply+post_persist);§6 API → T5;§7 前端(监听器/OS 通知/toast/权限/降级)→ T6+T7;§9 错误/边界 → T4(best-effort)+T7(seen/降级/多标签);§10 范围(不做 Web Push)→ 未进任务;§11 测试 → 各 Task TDD + T8。✅

**2. Placeholder 扫描**:无 TBD/TODO。迁移 revision `c2d3e4f5a6b7`、down_revision 取实测 head `b1c2d3e4f5a6`(已核)。✅

**3. 类型/签名一致性**:`list_undelivered(user_id)` / `mark_delivered(ids, user_id)`、`apply_notify_calls(session_id, new_messages)`、`notify_enabled`/`NotifyingExecutor`、`NotificationRead`/`MarkDeliveredRequest(ids)`、前端 `listNotifications`/`markNotificationsDelivered`、`Notification` 类型(前端别名 `AppNotification`)—— 全程一致。✅

**4. 风险点**(留给执行/审查):① 前端 `Notification` 类型名与 DOM 构造器同名 → 监听器用 `getNotif()` 取值 + `AppNotification` 别名,jsdom 无 Notification 时降级(T7 第 4 个测试覆盖);② 多标签页同一通知各弹一次(spec §9 已接受);③ post_persist 改 import + 元组,确保不漏 remember/schedule(既有测试兜底)。
