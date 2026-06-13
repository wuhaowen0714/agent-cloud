# 定时任务(Scheduled Tasks)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户(经 UI)或 agent(经 `schedule_task` 工具)创建定时任务,backend 进程内轮询器到点以指定 agent 跑一回合预设提示词,产物落成侧栏可见的新会话,并通过未读角标/管理面板/发起会话回执让发起者知道它跑了。

**Architecture:** 新 `scheduled_tasks` Postgres 表存规格+状态;backend `lifespan` 起一个 asyncio 轮询器,`SELECT ... FOR UPDATE SKIP LOCKED` 取到期任务、**先推进 `next_run_at` 再执行**(at-most-once)、陈旧周期任务快进跳过;每个到期任务建新会话并复用从 `api/turn.py` 抽出的无头回合执行器 `execute_turn_headless` 跑一回合;agent 工具照抄现有 `remember` 模式(worker 本地合成确认 + backend 扫 `new_messages` 落库,无 worker→backend 反向通道)。

**Tech Stack:** FastAPI + SQLAlchemy(async)+ Alembic + Postgres;croniter(cron 下次时间);gRPC(worker);React19 + Vite + TS + Tailwind + zustand + react-query(前端);pytest + testcontainers(后端测试);vitest + testing-library(前端测试)。

**Spec:** `docs/superpowers/specs/2026-06-13-scheduled-tasks-design.md`

---

## Shared Interface Contract(全程保持一致,防 Task 间签名漂移)

**模型 `ScheduledTask`**(`models/scheduled_task.py`,表 `scheduled_tasks`)列:
`id`(uuid pk)/ `user_id`(FK users CASCADE, index)/ `agent_config_id`(FK agent_configs CASCADE)/ `name`(Text)/ `prompt`(Text)/ `schedule_kind`(str: once|interval|cron)/ `schedule_expr`(str)/ `schedule_tz`(str, default `'Asia/Shanghai'`)/ `enabled`(bool, default True)/ `next_run_at`(timestamptz, nullable)/ `running_since`(timestamptz, nullable)/ `last_run_at`(timestamptz, nullable)/ `last_status`(str, nullable: ok|error|skipped)/ `last_error`(Text, nullable)/ `last_delivery_error`(Text, nullable)/ `last_run_session_id`(uuid FK sessions SET NULL, nullable)/ `origin_session_id`(uuid FK sessions SET NULL, nullable)/ `created_at`(TimestampMixin)/ `updated_at`(onupdate now)。
索引 `ix_scheduled_tasks_due`:`(enabled, next_run_at)` partial `WHERE next_run_at IS NOT NULL`。

**`sessions` 加两列**:`scheduled_task_id`(uuid FK scheduled_tasks SET NULL, **`use_alter=True`** 打破与 scheduled_tasks 的互引环, nullable)、`unread`(bool, NOT NULL, server_default false)。

**`scheduler/schedule.py`**:`class ScheduleError(ValueError)`;`validate_and_normalize(kind, expr, tz) -> str`(非法抛 `ScheduleError`);`first_run_at(kind, expr, tz, now) -> datetime|None`;`next_run_after(kind, expr, tz, *, prev, now) -> datetime|None`;`grace_seconds(kind, expr, tz, prev) -> float`;常量 `MIN_INTERVAL_SECONDS=60`。全部 UTC tz-aware。

**`ScheduledTaskRepository(BaseRepository[ScheduledTask])`**:`list_by_user(user_id)`、`get_owned(task_id, user_id)`、`select_due_for_update(now, limit, run_lease_seconds) -> list[ScheduledTask]`、`set_result(task_id, *, status, last_run_session_id, error, delivery_error)`。

**`SessionRepository`** 新增/改:`create_for(user_id, agent_config_id, title, *, scheduled_task_id=None, unread=False)`(扩参,旧调用不变)、`set_unread(session_id, value)`、`mark_read(session_id)`。

**`turn/headless.py`**:`@dataclass HeadlessResult(new_messages: list[Message], final_text: str, stop_reason: str, input_tokens: int, output_tokens: int)`;`class SessionBusy(Exception)`;`async execute_turn_headless(session_id, user_content, *, settings, manager, store, is_scheduled_run=False) -> HeadlessResult`(内部自管 DB session;try_acquire 失败抛 `SessionBusy`)。

**`scheduler/poller.py`**:`async scheduler_loop(settings)`、`async poll_once(settings) -> list[dict]`。**`scheduler/runner.py`**:`async run_scheduled_task(snap: dict, settings)`、常量 `CRON_HINT`。

**schemas `schemas/scheduled_task.py`**:`ScheduledTaskCreate`、`ScheduledTaskUpdate`、`ScheduledTaskRead`(`from_attributes=True`)。

**API `api/scheduled_tasks.py`** router prefix `/scheduled-tasks`:`GET ""`、`POST ""`、`PATCH /{id}`、`DELETE /{id}`、`POST /{id}/run-now`。**sessions 加** `POST /sessions/{id}/mark-read`。`SessionRead` 加 `scheduled_task_id`、`unread`。

**worker `schedule_task.py`**:`SCHEDULE_TASK_SPEC`、`schedule_task_enabled(enabled_tools)`、`class SchedulingExecutor`(仿 `RememberingExecutor`)。**proto**:`RunTurnRequest` 加 `bool is_scheduled_run = 13;`。**backend `turn/schedule_apply.py`**:`apply_schedule_task_calls(session_id, new_messages) -> int`;**`turn/post_persist.py`**:`run_tool_side_effects(session_id, new_messages)`(调 remember + schedule)。

**config 新增**:`scheduler_enabled=True`、`scheduler_poll_interval_seconds=30`、`scheduler_batch_size=10`、`scheduler_run_lease_seconds=900`、`scheduler_max_concurrent_runs=4`。

**前端**:`types.ts` `Session` 加 `scheduled_task_id: string|null`、`unread: boolean`,新增 `ScheduledTask`;`api/client.ts` 加 `listScheduledTasks/createScheduledTask/patchScheduledTask/deleteScheduledTask/runScheduledTask/markSessionRead`;`agentConfig.ts` `BUILTIN_TOOLS` 加 `schedule_task`;新 `components/ScheduledTasksPanel.tsx`;`TopBar.tsx` 加「定时任务」chip;`SessionList.tsx` 加未读点 + 定时标。

## 测试约定

- **后端单测命令**:`cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" <path> -v`。
- DB 测试用 conftest 的 `session`(AsyncSession on testcontainer)或 `auth_client`/`client`(ASGI + 已注册用户)或 `migration_pg_url`(独立空库)。
- 测**直接走全局 `get_sessionmaker()`** 的代码(poller/headless/apply)时,按既有套路把全局指到测试引擎:
  ```python
  def _patch_sessionmaker(monkeypatch, engine):
      import agent_cloud_backend.db as db_module
      from sqlalchemy.ext.asyncio import async_sessionmaker
      monkeypatch.setattr(db_module, "_sessionmaker", async_sessionmaker(engine, expire_on_commit=False))
  ```
- **worker 单测**:`cd services/worker && uv run pytest <path> -v`(纯单元,无需 Docker)。
- **前端**:`cd frontend && npm run lint`(tsc -b)+ `npx vitest run <path>`。
- **proto 重生成**:仓库根 `bash scripts/gen_protos.sh`(桩落 `packages/common/src/agent_cloud/v1/`,已提交)。

---

## Phase 1 — 数据层

### Task 1: `scheduler/schedule.py`(排期解析 + 下次时间)+ croniter 依赖

**Files:**
- Modify: `services/backend/pyproject.toml`(加 `croniter`)
- Create: `services/backend/src/agent_cloud_backend/scheduler/__init__.py`(空)
- Create: `services/backend/src/agent_cloud_backend/scheduler/schedule.py`
- Test: `services/backend/tests/test_schedule.py`

- [ ] **Step 1: 加依赖**

在 `services/backend/pyproject.toml` 的 `dependencies` 列表加一行 `"croniter>=2.0",`,然后:
```bash
cd services/backend && uv sync
```

- [ ] **Step 2: 写失败测试** `services/backend/tests/test_schedule.py`

```python
from datetime import UTC, datetime, timedelta

import pytest
from agent_cloud_backend.scheduler import schedule
from agent_cloud_backend.scheduler.schedule import ScheduleError

NOW = datetime(2026, 6, 13, 12, 0, 0, tzinfo=UTC)


def test_validate_once_normalizes_to_utc():
    out = schedule.validate_and_normalize("once", "2026-06-14T09:00:00+08:00", "Asia/Shanghai")
    assert out == "2026-06-14T01:00:00+00:00"  # +08 → UTC


def test_validate_interval_friendly_and_floor():
    assert schedule.validate_and_normalize("interval", "30m", "UTC") == "1800"
    assert schedule.validate_and_normalize("interval", "120", "UTC") == "120"
    with pytest.raises(ScheduleError):
        schedule.validate_and_normalize("interval", "30", "UTC")  # < 60s


def test_validate_cron_and_tz():
    assert schedule.validate_and_normalize("cron", "0 9 * * *", "Asia/Shanghai") == "0 9 * * *"
    with pytest.raises(ScheduleError):
        schedule.validate_and_normalize("cron", "not a cron", "UTC")
    with pytest.raises(ScheduleError):
        schedule.validate_and_normalize("cron", "0 9 * * *", "Mars/Phobos")


def test_validate_unknown_kind():
    with pytest.raises(ScheduleError):
        schedule.validate_and_normalize("weekly", "x", "UTC")


def test_first_run_at():
    assert schedule.first_run_at("interval", "1800", "UTC", NOW) == NOW + timedelta(seconds=1800)
    assert schedule.first_run_at("once", "2026-06-14T01:00:00+00:00", "UTC", NOW) == datetime(
        2026, 6, 14, 1, 0, tzinfo=UTC
    )
    # cron 0 9 * * * in +08 → 次日 09:00 +08 = 01:00 UTC
    nxt = schedule.first_run_at("cron", "0 9 * * *", "Asia/Shanghai", NOW)
    assert nxt == datetime(2026, 6, 14, 1, 0, tzinfo=UTC)


def test_next_run_after_once_is_none():
    assert schedule.next_run_after("once", "x", "UTC", prev=NOW, now=NOW) is None


def test_next_run_after_interval_preserves_phase_and_skips_missed():
    prev = NOW
    # 只过了一点 → 推进一个周期
    n1 = schedule.next_run_after("interval", "600", "UTC", prev=prev, now=NOW + timedelta(seconds=10))
    assert n1 == prev + timedelta(seconds=600)
    # 错过 3 个周期(停机)→ 直接跳到第 4 个相位点,不补积压
    n2 = schedule.next_run_after("interval", "600", "UTC", prev=prev, now=NOW + timedelta(seconds=1850))
    assert n2 == prev + timedelta(seconds=4 * 600)


def test_grace_seconds_clamped():
    assert schedule.grace_seconds("interval", "600", "UTC", NOW) == 300.0  # 600/2
    assert schedule.grace_seconds("interval", "120", "UTC", NOW) == 120.0  # 60 夹到下限 120
    assert schedule.grace_seconds("interval", "86400", "UTC", NOW) == 7200.0  # 夹到上限 2h
    assert schedule.grace_seconds("once", "x", "UTC", NOW) == 0.0  # once 永不快进跳过
```

- [ ] **Step 3: 跑测试确认 fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_schedule.py -v`
Expected: FAIL(`ModuleNotFoundError: agent_cloud_backend.scheduler`)

- [ ] **Step 4: 实现** `services/backend/src/agent_cloud_backend/scheduler/__init__.py`(空文件)+ `schedule.py`

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import ceil
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

MIN_INTERVAL_SECONDS = 60
_GRACE_MIN = 120.0
_GRACE_MAX = 7200.0
_FRIENDLY = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class ScheduleError(ValueError):
    """排期参数非法(kind/expr/tz)。创建时抛出 → API 422 / agent 工具拒绝。"""


def _tz(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ScheduleError(f"未知时区:{tz!r}") from e


def _parse_interval_seconds(expr: str) -> int:
    e = expr.strip().lower()
    if e.isdigit():
        return int(e)
    if len(e) >= 2 and e[-1] in _FRIENDLY and e[:-1].isdigit():
        return int(e[:-1]) * _FRIENDLY[e[-1]]
    raise ScheduleError(f"interval 必须是正整数秒或如 30m/2h/1d:{expr!r}")


def _parse_once_utc(expr: str) -> datetime:
    try:
        dt = datetime.fromisoformat(expr.strip())
    except ValueError as e:
        raise ScheduleError(f"once 时间必须是 ISO8601:{expr!r}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def validate_and_normalize(kind: str, expr: str, tz: str) -> str:
    """校验并归一化 schedule_expr;非法抛 ScheduleError。返回入库用的规范化 expr。"""
    if kind == "once":
        return _parse_once_utc(expr).isoformat()
    if kind == "interval":
        secs = _parse_interval_seconds(expr)
        if secs < MIN_INTERVAL_SECONDS:
            raise ScheduleError(f"interval 最小 {MIN_INTERVAL_SECONDS}s:{secs}")
        return str(secs)
    if kind == "cron":
        _tz(tz)
        if not croniter.is_valid(expr.strip()):
            raise ScheduleError(f"非法 cron 表达式:{expr!r}")
        return expr.strip()
    raise ScheduleError(f"未知 schedule_kind:{kind!r}")


def first_run_at(kind: str, expr: str, tz: str, now: datetime) -> datetime | None:
    """创建/恢复时算首次 next_run(UTC)。once 过去也返回原时刻(由调用方决定是否立即跑)。"""
    if kind == "once":
        return _parse_once_utc(expr)
    if kind == "interval":
        return now + timedelta(seconds=int(expr))
    if kind == "cron":
        return croniter(expr, now.astimezone(_tz(tz))).get_next(datetime).astimezone(UTC)
    raise ScheduleError(f"未知 schedule_kind:{kind!r}")


def next_run_after(
    kind: str, expr: str, tz: str, *, prev: datetime, now: datetime
) -> datetime | None:
    """一次运行后推进 next_run。once→None;interval→保相位推进到 >now(跳过错过的整数周期);
    cron→now 之后的下一次。全部 UTC。"""
    if kind == "once":
        return None
    if kind == "interval":
        step = int(expr)
        elapsed = (now - prev).total_seconds()
        n = max(1, ceil(elapsed / step)) if elapsed > 0 else 1
        return prev + timedelta(seconds=n * step)
    if kind == "cron":
        return croniter(expr, now.astimezone(_tz(tz))).get_next(datetime).astimezone(UTC)
    raise ScheduleError(f"未知 schedule_kind:{kind!r}")


def grace_seconds(kind: str, expr: str, tz: str, prev: datetime) -> float:
    """陈旧判定容差:周期的一半,夹在 [120s, 2h]。once→0(迟到也跑,绝不快进跳过)。"""
    if kind == "once":
        return 0.0
    if kind == "interval":
        period = float(int(expr))
    elif kind == "cron":
        it = croniter(expr, prev.astimezone(_tz(tz)))
        a = it.get_next(datetime)
        b = it.get_next(datetime)
        period = (b - a).total_seconds()
    else:
        raise ScheduleError(f"未知 schedule_kind:{kind!r}")
    return min(_GRACE_MAX, max(_GRACE_MIN, period / 2))
```

- [ ] **Step 5: 跑测试确认 pass**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_schedule.py -v`
Expected: PASS(9 passed)

- [ ] **Step 6: commit**

```bash
git add services/backend/pyproject.toml services/backend/uv.lock services/backend/src/agent_cloud_backend/scheduler/ services/backend/tests/test_schedule.py
git commit -m "feat(sched): schedule parsing + next-run math (once/interval/cron)"
```

---

### Task 2: `ScheduledTask` 模型 + `sessions` 两列 + 注册进 metadata

**Files:**
- Create: `services/backend/src/agent_cloud_backend/models/scheduled_task.py`
- Modify: `services/backend/src/agent_cloud_backend/models/session.py`(加 2 列)
- Modify: `services/backend/src/agent_cloud_backend/models/__init__.py`(import + `__all__`)
- Test: `services/backend/tests/test_scheduled_task_model.py`

- [ ] **Step 1: 写失败测试** `tests/test_scheduled_task_model.py`

```python
import uuid
from datetime import UTC, datetime, timedelta

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.scheduled_task import ScheduledTask
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.models.user import User


async def _user_agent(session) -> tuple[uuid.UUID, uuid.UUID]:
    u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
    session.add(u)
    await session.flush()
    a = AgentConfig(user_id=u.id, name="a", model="m", provider="p")
    session.add(a)
    await session.flush()
    return u.id, a.id


async def test_scheduled_task_row_roundtrip(session):
    uid, aid = await _user_agent(session)
    t = ScheduledTask(
        user_id=uid, agent_config_id=aid, name="每日新闻", prompt="总结今天的新闻",
        schedule_kind="cron", schedule_expr="0 9 * * *", schedule_tz="Asia/Shanghai",
        next_run_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(t)
    await session.commit()
    got = await session.get(ScheduledTask, t.id)
    assert got.enabled is True
    assert got.last_status is None
    assert got.running_since is None
    assert got.created_at is not None


async def test_session_has_scheduled_fields(session):
    uid, aid = await _user_agent(session)
    s = Session(user_id=uid, agent_config_id=aid, work_subdir="workspace")
    session.add(s)
    await session.commit()
    assert s.unread is False
    assert s.scheduled_task_id is None
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_scheduled_task_model.py -v`
Expected: FAIL(`ImportError: cannot import name 'ScheduledTask'`)

- [ ] **Step 3: 建模型** `services/backend/src/agent_cloud_backend/models/scheduled_task.py`

```python
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud_backend.models.base import Base, TimestampMixin, uuid_pk


class ScheduledTask(Base, TimestampMixin):
    __tablename__ = "scheduled_tasks"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    agent_config_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_configs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    schedule_kind: Mapped[str] = mapped_column(nullable=False)  # once | interval | cron
    schedule_expr: Mapped[str] = mapped_column(nullable=False)
    schedule_tz: Mapped[str] = mapped_column(default="Asia/Shanghai", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    running_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(nullable=True)  # ok | error | skipped
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    origin_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_scheduled_tasks_due",
            "enabled",
            "next_run_at",
            postgresql_where=(next_run_at.isnot(None)),
        ),
    )
```

> 注:`postgresql_where=(next_run_at.isnot(None))` 引用上面的 `mapped_column`;若 linter 抱怨前向引用,用字符串 `postgresql_where=text("next_run_at IS NOT NULL")` 并 `from sqlalchemy import text`。

- [ ] **Step 4: 给 `sessions` 加 2 列** —— 编辑 `models/session.py`,在 `last_context_tokens` 那行后加:

```python
    # 定时任务:本会话是某定时任务的一次运行产物(NULL=普通会话)。use_alter 打破与
    # scheduled_tasks 的互引环(create_all 拓扑排序遇环会报错)。
    scheduled_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scheduled_tasks.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    # 未读角标:仅定时运行产出的会话置 True;打开会话即清。
    unread: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
```

`models/session.py` 顶部 import 改为:
```python
from sqlalchemy import Boolean, DateTime, ForeignKey, func, text
```

- [ ] **Step 5: 注册进 metadata** —— `models/__init__.py` 加 import `from agent_cloud_backend.models.scheduled_task import ScheduledTask` 并把 `"ScheduledTask"` 加入 `__all__`(否则 `Base.metadata.create_all` 不含此表,测试建不出来)。

- [ ] **Step 6: 跑确认 pass**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_scheduled_task_model.py -v`
Expected: PASS(2 passed)

- [ ] **Step 7: commit**

```bash
git add services/backend/src/agent_cloud_backend/models/ services/backend/tests/test_scheduled_task_model.py
git commit -m "feat(sched): ScheduledTask model + sessions.scheduled_task_id/unread"
```

---

### Task 3: Alembic 迁移(建表 + 改 sessions)

**Files:**
- Create: `services/backend/alembic/versions/b1c2d3e4f5a6_scheduled_tasks.py`
- Test: `services/backend/tests/test_migration.py`(加一个用例)

- [ ] **Step 1: 写失败测试** —— 在 `tests/test_migration.py` 末尾追加:

```python
def test_scheduled_tasks_schema(migration_pg_url: str):
    import os
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    sync_url = migration_pg_url.replace("+asyncpg", "")
    os.environ["AGENT_CLOUD_DATABASE_URL"] = migration_pg_url
    command.upgrade(Config("alembic.ini"), "head")

    engine = create_engine(sync_url)
    with engine.connect() as conn:
        tables = {r[0] for r in conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        )}
        cols = {r[0] for r in conn.execute(text(
            "SELECT table_name||'.'||column_name FROM information_schema.columns "
            "WHERE table_schema='public'"
        ))}
        idx = {r[0] for r in conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE schemaname='public' "
            "AND tablename='scheduled_tasks'"
        ))}
    assert "scheduled_tasks" in tables
    assert "sessions.scheduled_task_id" in cols
    assert "sessions.unread" in cols
    assert "ix_scheduled_tasks_due" in idx
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_migration.py::test_scheduled_tasks_schema -v`
Expected: FAIL(`scheduled_tasks` 不在 tables)

- [ ] **Step 3: 写迁移** `services/backend/alembic/versions/b1c2d3e4f5a6_scheduled_tasks.py`

```python
"""scheduled tasks

Revision ID: b1c2d3e4f5a6
Revises: d5e6f7a8b9c0
Create Date: 2026-06-13
"""
import sqlalchemy as sa
from alembic import op

revision = "b1c2d3e4f5a6"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduled_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_config_id", sa.Uuid(), sa.ForeignKey("agent_configs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("schedule_kind", sa.String(), nullable=False),
        sa.Column("schedule_expr", sa.String(), nullable=False),
        sa.Column("schedule_tz", sa.String(), nullable=False, server_default="Asia/Shanghai"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("running_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_delivery_error", sa.Text(), nullable=True),
        sa.Column("last_run_session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("origin_session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_scheduled_tasks_user_id", "scheduled_tasks", ["user_id"])
    op.create_index(
        "ix_scheduled_tasks_due",
        "scheduled_tasks",
        ["enabled", "next_run_at"],
        postgresql_where=sa.text("next_run_at IS NOT NULL"),
    )
    op.add_column("sessions", sa.Column("scheduled_task_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_sessions_scheduled_task_id", "sessions", "scheduled_tasks",
        ["scheduled_task_id"], ["id"], ondelete="SET NULL",
    )
    op.add_column(
        "sessions", sa.Column("unread", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    op.drop_constraint("fk_sessions_scheduled_task_id", "sessions", type_="foreignkey")
    op.drop_column("sessions", "unread")
    op.drop_column("sessions", "scheduled_task_id")
    op.drop_index("ix_scheduled_tasks_due", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_user_id", table_name="scheduled_tasks")
    op.drop_table("scheduled_tasks")
```

- [ ] **Step 4: 跑确认 pass**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_migration.py -v`
Expected: PASS(原有用例 + 新 `test_scheduled_tasks_schema` 全过)

- [ ] **Step 5: commit**

```bash
git add services/backend/alembic/versions/b1c2d3e4f5a6_scheduled_tasks.py services/backend/tests/test_migration.py
git commit -m "feat(sched): alembic migration for scheduled_tasks + sessions columns"
```

---

### Task 4: 仓库(`ScheduledTaskRepository` + `SessionRepository` 扩展)

**Files:**
- Create: `services/backend/src/agent_cloud_backend/repositories/scheduled_task.py`
- Modify: `services/backend/src/agent_cloud_backend/repositories/session.py`(`create_for` 扩参 + `set_unread`/`mark_read`)
- Test: `services/backend/tests/test_scheduled_task_repo.py`

- [ ] **Step 1: 写失败测试** `tests/test_scheduled_task_repo.py`

```python
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.scheduled_task import ScheduledTask
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.scheduled_task import ScheduledTaskRepository
from agent_cloud_backend.repositories.session import SessionRepository
from sqlalchemy.ext.asyncio import async_sessionmaker


async def _seed(session) -> tuple[uuid.UUID, uuid.UUID]:
    u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
    session.add(u)
    await session.flush()
    a = AgentConfig(user_id=u.id, name="a", model="m", provider="p")
    session.add(a)
    await session.flush()
    return u.id, a.id


def _task(uid, aid, **kw) -> ScheduledTask:
    base = dict(
        user_id=uid, agent_config_id=aid, name="t", prompt="p",
        schedule_kind="interval", schedule_expr="600", schedule_tz="UTC",
    )
    base.update(kw)
    return ScheduledTask(**base)


async def test_list_by_user_scopes(session):
    uid, aid = await _seed(session)
    other, _ = await _seed(session)
    session.add(_task(uid, aid, name="mine"))
    session.add(_task(other, aid, name="theirs"))
    await session.commit()
    rows = await ScheduledTaskRepository(session).list_by_user(uid)
    assert [r.name for r in rows] == ["mine"]


async def test_select_due_only_enabled_past_and_not_running(session):
    uid, aid = await _seed(session)
    now = datetime.now(UTC)
    due = _task(uid, aid, name="due", next_run_at=now - timedelta(seconds=5))
    future = _task(uid, aid, name="future", next_run_at=now + timedelta(hours=1))
    disabled = _task(uid, aid, name="off", enabled=False, next_run_at=now - timedelta(seconds=5))
    running = _task(uid, aid, name="busy", next_run_at=now - timedelta(seconds=5),
                    running_since=now - timedelta(seconds=1))
    for t in (due, future, disabled, running):
        session.add(t)
    await session.commit()
    rows = await ScheduledTaskRepository(session).select_due_for_update(now, limit=10, run_lease_seconds=900)
    assert {r.name for r in rows} == {"due"}


async def test_select_due_running_lease_expired_is_reclaimed(session):
    uid, aid = await _seed(session)
    now = datetime.now(UTC)
    stale = _task(uid, aid, name="stale", next_run_at=now - timedelta(seconds=5),
                  running_since=now - timedelta(seconds=1000))  # > 900 lease
    session.add(stale)
    await session.commit()
    rows = await ScheduledTaskRepository(session).select_due_for_update(now, limit=10, run_lease_seconds=900)
    assert {r.name for r in rows} == {"stale"}


async def test_skip_locked_no_double_claim(engine):
    """两个并发事务对同一到期任务:SKIP LOCKED 保证只有一个拿到。"""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        uid, aid = await _seed(s)
        now = datetime.now(UTC)
        s.add(_task(uid, aid, name="solo", next_run_at=now - timedelta(seconds=5)))
        await s.commit()

    async def claim(barrier):
        async with maker() as db:
            rows = await ScheduledTaskRepository(db).select_due_for_update(
                datetime.now(UTC), limit=10, run_lease_seconds=900
            )
            await barrier.wait()  # 两个事务都进来后再各自提交,确保锁重叠
            await db.commit()
            return [r.name for r in rows]

    barrier = asyncio.Barrier(2)
    a, b = await asyncio.gather(claim(barrier), claim(barrier))
    assert sorted([len(a), len(b)]) == [0, 1]  # 一个拿到、一个被 SKIP


async def test_set_result(session):
    uid, aid = await _seed(session)
    t = _task(uid, aid, running_since=datetime.now(UTC))
    session.add(t)
    await session.commit()
    await ScheduledTaskRepository(session).set_result(
        t.id, status="ok", last_run_session_id=None, error=None, delivery_error=None
    )
    await session.commit()
    got = await session.get(ScheduledTask, t.id)
    assert got.last_status == "ok"
    assert got.running_since is None
    assert got.last_run_at is not None


async def test_session_create_for_scheduled_fields(session):
    uid, aid = await _seed(session)
    tid = uuid.uuid4()
    # 先建任务行供 FK 指向
    session.add(_task(uid, aid))
    repo = SessionRepository(session)
    s = await repo.create_for(uid, aid, "title", scheduled_task_id=None, unread=True)
    await session.commit()
    assert s.unread is True
    await repo.mark_read(s.id)
    await session.commit()
    await session.refresh(s)
    assert s.unread is False
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_scheduled_task_repo.py -v`
Expected: FAIL(`ImportError: ScheduledTaskRepository`)

- [ ] **Step 3: 建仓库** `services/backend/src/agent_cloud_backend/repositories/scheduled_task.py`

```python
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from agent_cloud_backend.models.scheduled_task import ScheduledTask
from agent_cloud_backend.repositories.base import BaseRepository


class ScheduledTaskRepository(BaseRepository[ScheduledTask]):
    model = ScheduledTask

    async def list_by_user(self, user_id: uuid.UUID) -> list[ScheduledTask]:
        result = await self.session.execute(
            select(ScheduledTask)
            .where(ScheduledTask.user_id == user_id)
            .order_by(ScheduledTask.created_at, ScheduledTask.id)
        )
        return list(result.scalars().all())

    async def get_owned(self, task_id: uuid.UUID, user_id: uuid.UUID) -> ScheduledTask | None:
        t = await self.session.get(ScheduledTask, task_id)
        return t if t is not None and t.user_id == user_id else None

    async def select_due_for_update(
        self, now: datetime, *, limit: int, run_lease_seconds: int
    ) -> list[ScheduledTask]:
        """到期且未在跑(或租约已过)的任务,加行锁、跳过别人锁住的(多副本安全)。"""
        from datetime import timedelta

        lease_cutoff = now - timedelta(seconds=run_lease_seconds)
        result = await self.session.execute(
            select(ScheduledTask)
            .where(
                ScheduledTask.enabled.is_(True),
                ScheduledTask.next_run_at.isnot(None),
                ScheduledTask.next_run_at <= now,
                (ScheduledTask.running_since.is_(None))
                | (ScheduledTask.running_since < lease_cutoff),
            )
            .order_by(ScheduledTask.next_run_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def set_result(
        self,
        task_id: uuid.UUID,
        *,
        status: str,
        last_run_session_id: uuid.UUID | None,
        error: str | None,
        delivery_error: str | None,
    ) -> None:
        """回写一次运行结果并清 running_since(单条 UPDATE,不读 ORM 对象)。"""
        await self.session.execute(
            update(ScheduledTask)
            .where(ScheduledTask.id == task_id)
            .values(
                last_run_at=datetime.now(UTC),
                last_status=status,
                last_run_session_id=last_run_session_id,
                last_error=error,
                last_delivery_error=delivery_error,
                running_since=None,
            )
        )
```

- [ ] **Step 4: 扩展 `SessionRepository`** —— 编辑 `repositories/session.py`。`create_for` 改为:

```python
    async def create_for(
        self,
        user_id: uuid.UUID,
        agent_config_id: uuid.UUID,
        title: str | None,
        *,
        scheduled_task_id: uuid.UUID | None = None,
        unread: bool = False,
    ) -> Session:
        s = Session(
            id=uuid.uuid4(),
            user_id=user_id,
            agent_config_id=agent_config_id,
            title=title,
            work_subdir="workspace",
            scheduled_task_id=scheduled_task_id,
            unread=unread,
        )
        self.session.add(s)
        await self.session.flush()
        return s
```

并加两个方法(放在 `release` 附近):

```python
    async def set_unread(self, session_id: uuid.UUID, value: bool) -> None:
        await self.session.execute(
            update(Session).where(Session.id == session_id).values(unread=value)
        )

    async def mark_read(self, session_id: uuid.UUID) -> None:
        await self.set_unread(session_id, False)
```

(`update` 已在 `repositories/session.py` 顶部 import。)

- [ ] **Step 5: 跑确认 pass**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_scheduled_task_repo.py -v`
Expected: PASS(6 passed)

- [ ] **Step 6: 全量回归(Phase 1 收口)**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q`
Expected: 全绿(含既有用例 —— `create_for` 扩参不破坏旧调用)

- [ ] **Step 7: commit**

```bash
git add services/backend/src/agent_cloud_backend/repositories/ services/backend/tests/test_scheduled_task_repo.py
git commit -m "feat(sched): ScheduledTaskRepository (due/SKIP LOCKED) + SessionRepository unread"
```

---

## Phase 2 — 调度器 + 无头执行器

### Task 5: config 调度器配置项

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/config.py`
- Test: `services/backend/tests/test_config_scheduler.py`

- [ ] **Step 1: 写失败测试** `tests/test_config_scheduler.py`

```python
from agent_cloud_backend.config import Settings


def test_scheduler_defaults():
    s = Settings(_env_file=None)
    assert s.scheduler_enabled is True
    assert s.scheduler_poll_interval_seconds == 30
    assert s.scheduler_batch_size == 10
    assert s.scheduler_run_lease_seconds == 900
    assert s.scheduler_max_concurrent_runs == 4


def test_scheduler_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("AGENT_CLOUD_SCHEDULER_POLL_INTERVAL_SECONDS", "5")
    s = Settings()
    assert s.scheduler_enabled is False
    assert s.scheduler_poll_interval_seconds == 5
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_config_scheduler.py -v`
Expected: FAIL(`AttributeError: scheduler_enabled`)

- [ ] **Step 3: 实现** —— `config.py` 在 `default_agent_model` 那行后加:

```python
    # ── 定时任务(spec 2026-06-13-scheduled-tasks)──
    scheduler_enabled: bool = True  # 进程内轮询器开关(多副本可全开,SKIP LOCKED 防重复触发)
    scheduler_poll_interval_seconds: int = 30  # 轮询周期(子分钟精度无必要)
    scheduler_batch_size: int = 10  # 单轮最多取多少到期任务
    scheduler_run_lease_seconds: int = 900  # running_since 租约:超时即视为崩溃残留可重取
    scheduler_max_concurrent_runs: int = 4  # 单轮并发执行回合上限
```

- [ ] **Step 4: 跑确认 pass + commit**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_config_scheduler.py -v`
Expected: PASS
```bash
git add services/backend/src/agent_cloud_backend/config.py services/backend/tests/test_config_scheduler.py
git commit -m "feat(sched): scheduler config settings"
```

---

### Task 6: 抽 `execute_turn_headless` + 非流式端点改薄

**Files:**
- Create: `services/backend/src/agent_cloud_backend/turn/headless.py`
- Modify: `services/backend/src/agent_cloud_backend/api/turn.py`(`run_turn_endpoint` 改为薄包一层)
- Modify: `services/backend/tests/conftest.py`(给 `_quiet_title_generation` 加 headless 一处)
- Test: `services/backend/tests/test_headless_turn.py`(新)+ 既有 `tests/test_turn_endpoint.py` 必须仍绿(行为保持)

- [ ] **Step 1: 建 `turn/headless.py`**(从端点抽出的核心;内部自管 DB session,供 HTTP 端点与轮询器共用)

```python
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

import grpc
from agent_cloud_common.codec import msg_from_proto

from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.repositories.skill import AgentSkillEnableRepository
from agent_cloud_backend.skills.materialize import materialize_enabled_skills
from agent_cloud_backend.turn.assemble import build_run_turn_request
from agent_cloud_backend.turn.compaction import force_compact, maybe_compact_after_turn
from agent_cloud_backend.turn.heartbeat import session_heartbeat
from agent_cloud_backend.turn.memory_extract import apply_remember_calls
from agent_cloud_backend.turn.messages import common_to_content
from agent_cloud_backend.turn.retry import RetryAction, RetryPolicy, classify
from agent_cloud_backend.turn.title import spawn_title_generation
from agent_cloud_backend.turn.worker_client import run_turn_via_worker

logger = logging.getLogger(__name__)


class SessionBusy(Exception):
    """try_acquire 失败:会话被并发回合占用。"""


class HeadlessOverflow(Exception):
    """上下文压无可压(多轮压缩仍超窗)。"""


class HeadlessWorkerError(Exception):
    def __init__(self, code) -> None:
        self.code = code


@dataclass
class HeadlessResult:
    new_messages: list[Message]
    final_text: str
    stop_reason: str
    input_tokens: int
    output_tokens: int


async def execute_turn_headless(
    session_id: uuid.UUID, user_content: str, *, settings, manager, store
) -> HeadlessResult:
    """无头执行一回合:加锁→落用户消息→组装→worker(带重试/压缩)→落 new_messages + remember
    副作用→回合后压缩→起名→释放锁。HTTP 非流式端点与定时任务轮询器共用。内部自管 DB session。
    try_acquire 失败抛 SessionBusy;超窗到底抛 HeadlessOverflow;worker 不可恢复抛 HeadlessWorkerError。
    """
    async with get_sessionmaker()() as db:
        if not await SessionRepository(db).try_acquire(session_id):
            await db.rollback()
            raise SessionBusy()
        await db.commit()
    try:
        async with get_sessionmaker()() as db:
            user_msg = await MessageRepository(db).append(
                session_id,
                Message(
                    session_id=session_id, seq=0, role="user",
                    content={"text": user_content, "tool_calls": [], "tool_results": []},
                ),
            )
            await db.commit()
            user_msg_id = user_msg.id

        async def _assemble():
            async with get_sessionmaker()() as db:
                s = await SessionRepository(db).get(session_id)
                conn = await manager.get_endpoint_for_user(s.user_id)
                skills = await AgentSkillEnableRepository(db).list_enabled_for_agent(s.agent_config_id)
                materialize_enabled_skills(
                    base_root=Path(settings.sandbox_base_root), user_id=s.user_id,
                    work_subdir=s.work_subdir, skills=skills, store=store,
                )
                wd = "." if settings.sandbox_provisioner == "docker" else s.work_subdir
                return await build_run_turn_request(
                    db, s, sandbox_endpoint=conn.endpoint, sandbox_token=conn.token,
                    user_message=user_content, exclude_message_id=user_msg_id,
                    enabled_skills=skills, work_subdir=wd,
                )

        policy = RetryPolicy.from_settings(settings)
        overflow_used = transient_used = total_used = 0
        current = await _assemble()
        model = current.agent.model
        async with session_heartbeat(session_id, settings.session_heartbeat_seconds):
            while True:
                total_used += 1
                try:
                    response = await run_turn_via_worker(settings.worker_endpoint, current)
                    break
                except grpc.aio.AioRpcError as exc:
                    action = policy.decide(
                        exc.code(), overflow_used=overflow_used,
                        transient_used=transient_used, total_used=total_used,
                    )
                    if action == RetryAction.COMPACT_RETRY:
                        if not await force_compact(session_id, settings=settings):
                            raise HeadlessOverflow() from exc
                        overflow_used += 1
                        current = await _assemble()
                        continue
                    if action == RetryAction.BACKOFF_RETRY:
                        await asyncio.sleep(policy.backoff_seconds(transient_used))
                        transient_used += 1
                        continue
                    if classify(exc.code()) == "overflow":
                        raise HeadlessOverflow() from exc
                    raise HeadlessWorkerError(exc.code()) from exc

        commons = [msg_from_proto(p) for p in response.new_messages]
        persisted: list[Message] = []
        async with get_sessionmaker()() as db:
            repo = MessageRepository(db)
            for common in commons:
                row = await repo.append(
                    session_id,
                    Message(
                        session_id=session_id, seq=0, role=common.role.value,
                        content=common_to_content(common),
                    ),
                )
                persisted.append(row)
            await SessionRepository(db).set_context_tokens(session_id, response.context_tokens)
            await db.commit()
        # agent 主动记忆(独立事务、best-effort)。Phase 4 起换成 run_tool_side_effects(含 schedule_task)。
        try:
            await apply_remember_calls(session_id, commons)
        except Exception:
            logger.exception("apply_remember_calls failed for session %s", session_id)

        async with session_heartbeat(session_id, settings.session_heartbeat_seconds):
            await maybe_compact_after_turn(
                session_id, response.context_tokens, model=model, settings=settings
            )
        async with get_sessionmaker()() as db:
            s = await SessionRepository(db).get(session_id)
            if s.title is None:
                spawn_title_generation(session_id, settings=settings)

        final_text = next(
            (m.content.get("text", "") for m in reversed(persisted) if m.role == "assistant"), ""
        )
        return HeadlessResult(
            new_messages=persisted, final_text=final_text, stop_reason=response.stop_reason,
            input_tokens=response.input_tokens, output_tokens=response.output_tokens,
        )
    finally:
        async with get_sessionmaker()() as db:
            try:
                await SessionRepository(db).release(session_id)
                await db.commit()
            except Exception:
                logger.exception("headless: release lock failed for %s", session_id)
```

- [ ] **Step 2: 端点改薄** —— 把 `api/turn.py` 的 `run_turn_endpoint`(整段 body,line 54-206)替换为:

```python
@router.post("", response_model=TurnResponse)
async def run_turn_endpoint(
    session_id: uuid.UUID,
    body: TurnRequest,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    manager: SandboxManager = Depends(get_sandbox_manager),
    store: ObjectStore = Depends(get_object_store),
    user: User = Depends(get_current_user),
):
    await owned_session(session_id, user.id, db)  # 404 if missing or not owned
    try:
        result = await execute_turn_headless(
            session_id, body.content, settings=settings, manager=manager, store=store
        )
    except SessionBusy as exc:
        raise HTTPException(status_code=409, detail="session is busy") from exc
    except HeadlessOverflow as exc:
        raise HTTPException(
            status_code=413, detail="context too large to compact; please start a new session"
        ) from exc
    except HeadlessWorkerError as exc:
        if classify(exc.code) == "transient":
            raise HTTPException(status_code=503, detail="service unavailable, please retry") from exc
        raise HTTPException(status_code=502, detail=f"worker unavailable: {exc.code.name}") from exc
    return TurnResponse(
        messages=result.new_messages,
        stop_reason=result.stop_reason,
        usage=TurnUsage(input_tokens=result.input_tokens, output_tokens=result.output_tokens),
    )
```

然后清理 `api/turn.py` 顶部 import:删掉只被旧 body 用到的 `asyncio`、`Path`、`grpc`、`msg_from_proto`、`build_run_turn_request`、`force_compact`/`maybe_compact_after_turn`、`session_heartbeat`、`materialize_enabled_skills`、`common_to_content`、`RetryAction/RetryPolicy`、`run_turn_via_worker`、`spawn_title_generation`、`AgentSkillEnableRepository`、`MessageRepository`、`Message`、`Path`(逐个核对:**流式端点仍在用** `get_sessionmaker`、`ActiveTurn`/`TurnHub`/`subscribe`、`run_turn`、`build_run_turn_request`、`materialize_enabled_skills`、`AgentSkillEnableRepository`、`MessageRepository`、`Message`、`Path` —— 这些**保留**)。新增 import:
```python
from agent_cloud_backend.turn.headless import (
    HeadlessOverflow,
    HeadlessWorkerError,
    SessionBusy,
    execute_turn_headless,
)
from agent_cloud_backend.turn.retry import classify
```
> `classify` 端点映射 503/502 用。删 import 时:`RetryAction/RetryPolicy/run_turn_via_worker/grpc/asyncio` 等若流式端点不再直接用则删,但**流式 `stream_turn_endpoint` 仍用的**(`get_sessionmaker`、hub、`run_turn`、`build_run_turn_request`、`materialize_enabled_skills`、`AgentSkillEnableRepository`、`MessageRepository`、`Message`、`Path`)一律保留。以 `ruff check` 为准逐个清。

- [ ] **Step 3: conftest 加 headless 的 title 静音** —— `tests/conftest.py` 的 `_quiet_title_generation` 里,加第三处 setattr(端点已不再直接持有该名,改静音 headless 与 runner 两处):

```python
    monkeypatch.setattr(
        "agent_cloud_backend.turn.headless.spawn_title_generation", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "agent_cloud_backend.turn.runner.spawn_title_generation", lambda *a, **k: None
    )
```
> 删掉原来对 `agent_cloud_backend.api.turn.spawn_title_generation` 的 setattr(端点不再 import 它,否则 AttributeError)。

- [ ] **Step 4: 既有端点回归(行为保持的安全网)**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_turn_endpoint.py tests/test_turn_e2e.py -v`
Expected: PASS(抽取是行为保持重构,既有端点测试必须仍全绿)

- [ ] **Step 5: 写 headless 直测** `tests/test_headless_turn.py`(验证脱离 HTTP 直接可用 —— 轮询器的用法)

```python
import uuid

import pytest
from agent_cloud_backend.config import Settings
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.turn import headless as H
from agent_cloud_common import Message as CMessage
from agent_cloud_common import Role
from agent_cloud_common.codec import msg_to_proto
from sqlalchemy.ext.asyncio import async_sessionmaker


class _FakeConn:
    endpoint = "fake:50051"
    token = ""


class _FakeManager:
    async def get_endpoint_for_user(self, user_id):
        return _FakeConn()


class _FakeResp:
    def __init__(self, msgs):
        self.new_messages = msgs
        self.context_tokens = 123
        self.stop_reason = "end_turn"
        self.input_tokens = 10
        self.output_tokens = 5


async def test_execute_turn_headless_persists_and_returns_final_text(engine, monkeypatch, tmp_path):
    import agent_cloud_backend.db as db_module
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_sessionmaker", maker)
    # 重活打桩:沙箱物化/压缩/起名 都 no-op;worker 返回一条 assistant 消息
    monkeypatch.setattr(H, "materialize_enabled_skills", lambda **k: None)

    async def _no_compact(*a, **k):
        return None

    monkeypatch.setattr(H, "maybe_compact_after_turn", _no_compact)

    async def _fake_worker(endpoint, request):
        return _FakeResp([msg_to_proto(CMessage(role=Role.ASSISTANT, text="今日要点:无新增"))])

    monkeypatch.setattr(H, "run_turn_via_worker", _fake_worker)

    async with maker() as s:
        u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
        s.add(u)
        await s.flush()
        a = AgentConfig(user_id=u.id, name="a", model="m", provider="p")
        s.add(a)
        await s.flush()
        sess = await SessionRepository(s).create_for(u.id, a.id, "t")
        await s.commit()
        sid = sess.id

    res = await H.execute_turn_headless(
        sid, "跑个任务",
        settings=Settings(_env_file=None), manager=_FakeManager(), store=object(),
    )
    assert res.final_text == "今日要点:无新增"
    assert res.stop_reason == "end_turn"
    # 锁已释放
    async with maker() as s:
        got = await SessionRepository(s).get(sid)
        assert got.status == "idle"


async def test_execute_turn_headless_busy_raises(engine, monkeypatch):
    import agent_cloud_backend.db as db_module
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_sessionmaker", maker)
    async with maker() as s:
        u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
        s.add(u)
        await s.flush()
        a = AgentConfig(user_id=u.id, name="a", model="m", provider="p")
        s.add(a)
        await s.flush()
        sess = await SessionRepository(s).create_for(u.id, a.id, "t")
        await SessionRepository(s).try_acquire(sess.id)  # 先占锁
        await s.commit()
        sid = sess.id
    with pytest.raises(H.SessionBusy):
        await H.execute_turn_headless(
            sid, "x", settings=Settings(_env_file=None), manager=_FakeManager(), store=object()
        )
```

- [ ] **Step 6: 跑确认 pass + commit**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_headless_turn.py -v`
Expected: PASS(2 passed)
```bash
cd services/backend && ruff check src/agent_cloud_backend/api/turn.py src/agent_cloud_backend/turn/headless.py
git add services/backend/src/agent_cloud_backend/turn/headless.py services/backend/src/agent_cloud_backend/api/turn.py services/backend/tests/conftest.py services/backend/tests/test_headless_turn.py
git commit -m "refactor(turn): extract execute_turn_headless; thin non-streaming endpoint"
```

---

### Task 7: `run_scheduled_task`(建会话 + 跑回合 + [SILENT] + 状态回写 + 回执)

**Files:**
- Create: `services/backend/src/agent_cloud_backend/scheduler/runner.py`
- Test: `services/backend/tests/test_scheduled_runner.py`

- [ ] **Step 1: 写失败测试** `tests/test_scheduled_runner.py`

```python
import uuid
from datetime import UTC, datetime

from agent_cloud_backend.config import Settings
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.scheduled_task import ScheduledTask
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.scheduler import runner as R
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker


async def _seed(maker, *, with_origin=False):
    async with maker() as s:
        u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
        s.add(u); await s.flush()
        a = AgentConfig(user_id=u.id, name="a", model="m", provider="p")
        s.add(a); await s.flush()
        origin = None
        if with_origin:
            o = await SessionRepository(s).create_for(u.id, a.id, "chat")
            origin = o.id
        t = ScheduledTask(user_id=u.id, agent_config_id=a.id, name="新闻", prompt="总结",
                          schedule_kind="interval", schedule_expr="600", schedule_tz="UTC",
                          running_since=datetime.now(UTC), origin_session_id=origin)
        s.add(t); await s.flush()
        await s.commit()
        return dict(id=t.id, user_id=u.id, agent_config_id=a.id, name="新闻",
                    prompt="总结", origin_session_id=origin)


def _patch_headless(monkeypatch, final_text):
    async def _fake(session_id, user_content, *, settings, manager, store, **kw):
        from agent_cloud_backend.turn.headless import HeadlessResult
        return HeadlessResult(new_messages=[], final_text=final_text,
                              stop_reason="end_turn", input_tokens=0, output_tokens=0)
    monkeypatch.setattr(R, "execute_turn_headless", _fake)
    monkeypatch.setattr(R, "get_sandbox_manager", lambda: object())
    monkeypatch.setattr(R, "get_object_store", lambda: object())


async def test_run_creates_unread_session_and_marks_ok(engine, monkeypatch):
    import agent_cloud_backend.db as db_module
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_sessionmaker", maker)
    snap = await _seed(maker)
    _patch_headless(monkeypatch, "今天大事三件……")

    await R.run_scheduled_task(snap, Settings(_env_file=None))

    async with maker() as s:
        t = await s.get(ScheduledTask, snap["id"])
        assert t.last_status == "ok"
        assert t.running_since is None
        assert t.last_run_session_id is not None
        run = await s.get(__import__("agent_cloud_backend.models.session", fromlist=["Session"]).Session, t.last_run_session_id)
        assert run.scheduled_task_id == snap["id"]
        assert run.unread is True
        assert run.title.startswith("📅 新闻")


async def test_silent_marks_skipped_and_clears_unread(engine, monkeypatch):
    import agent_cloud_backend.db as db_module
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_sessionmaker", maker)
    snap = await _seed(maker)
    _patch_headless(monkeypatch, "[SILENT]")

    await R.run_scheduled_task(snap, Settings(_env_file=None))
    async with maker() as s:
        t = await s.get(ScheduledTask, snap["id"])
        assert t.last_status == "skipped"
        run = await s.get(__import__("agent_cloud_backend.models.session", fromlist=["Session"]).Session, t.last_run_session_id)
        assert run.unread is False


async def test_failure_marks_error_keeps_task(engine, monkeypatch):
    import agent_cloud_backend.db as db_module
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_sessionmaker", maker)
    snap = await _seed(maker)

    async def _boom(*a, **k):
        raise RuntimeError("worker down")
    monkeypatch.setattr(R, "execute_turn_headless", _boom)
    monkeypatch.setattr(R, "get_sandbox_manager", lambda: object())
    monkeypatch.setattr(R, "get_object_store", lambda: object())

    await R.run_scheduled_task(snap, Settings(_env_file=None))
    async with maker() as s:
        t = await s.get(ScheduledTask, snap["id"])
        assert t.last_status == "error"
        assert "worker down" in (t.last_error or "")


async def test_receipt_appended_to_idle_origin(engine, monkeypatch):
    import agent_cloud_backend.db as db_module
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_sessionmaker", maker)
    snap = await _seed(maker, with_origin=True)
    _patch_headless(monkeypatch, "结果")

    await R.run_scheduled_task(snap, Settings(_env_file=None))
    async with maker() as s:
        msgs = await MessageRepository(s).list_by_session(snap["origin_session_id"])
        assert any("已运行" in m.content["text"] for m in msgs)
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_scheduled_runner.py -v`
Expected: FAIL(`ModuleNotFoundError: scheduler.runner`)

- [ ] **Step 3: 实现** `services/backend/src/agent_cloud_backend/scheduler/runner.py`

```python
from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from agent_cloud_backend.config import Settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.scheduled_task import ScheduledTaskRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.sandbox.deps import get_sandbox_manager
from agent_cloud_backend.skills.deps import get_object_store
from agent_cloud_backend.turn.headless import SessionBusy, execute_turn_headless

logger = logging.getLogger(__name__)

CRON_HINT = (
    "[你正作为定时任务运行。把你的报告/结果作为最终回复产出即可,系统会自动呈现给用户;"
    "不要自己尝试投递。若确实没有新内容可报,只回复 [SILENT](别的什么都不写)。]"
)
_BJ = ZoneInfo("Asia/Shanghai")


async def run_scheduled_task(snap: dict, settings: Settings) -> None:
    """执行一个到期定时任务:建新会话 → 跑无头回合 → [SILENT]/状态回写 → 回执。

    snap: {id, user_id, agent_config_id, name, prompt, origin_session_id}。
    next_run_at 已由轮询器在执行前推进(at-most-once),这里只管跑 + 回写状态。
    """
    name = snap["name"]
    stamp = datetime.now(UTC).astimezone(_BJ).strftime("%m-%d %H:%M")
    title = f"📅 {name} · {stamp}"
    async with get_sessionmaker()() as db:
        s = await SessionRepository(db).create_for(
            snap["user_id"], snap["agent_config_id"], title,
            scheduled_task_id=snap["id"], unread=True,
        )
        await db.commit()
        session_id = s.id

    status, error, delivery_error = "ok", None, None
    try:
        result = await execute_turn_headless(
            session_id, f"{CRON_HINT}\n\n{snap['prompt']}",
            settings=settings, manager=get_sandbox_manager(), store=get_object_store(),
        )
        if result.final_text.strip().startswith("[SILENT]"):
            status = "skipped"
    except SessionBusy:
        status, error = "error", "session busy"
    except Exception as exc:
        logger.exception("scheduled task %s run failed", snap["id"])
        status, error = "error", str(exc)[:2000]

    if status == "skipped":
        async with get_sessionmaker()() as db:
            await SessionRepository(db).set_unread(session_id, False)
            await db.commit()

    # 回执(仅 agent 排的期 + 跑成了 + 发起会话空闲,避免与活跃回合抢 seq)
    origin = snap.get("origin_session_id")
    if origin and status == "ok":
        try:
            async with get_sessionmaker()() as db:
                o = await SessionRepository(db).get(origin)
                if o is not None and o.status == "idle":
                    await MessageRepository(db).append(
                        origin,
                        Message(
                            session_id=origin, seq=0, role="assistant",
                            content={
                                "text": f"📅 定时任务「{name}」已运行 → 结果见新会话",
                                "tool_calls": [], "tool_results": [],
                            },
                        ),
                    )
                    await db.commit()
        except Exception:
            logger.exception("scheduled task %s receipt failed", snap["id"])
            delivery_error = "receipt append failed"

    async with get_sessionmaker()() as db:
        await ScheduledTaskRepository(db).set_result(
            snap["id"], status=status, last_run_session_id=session_id,
            error=error, delivery_error=delivery_error,
        )
        await db.commit()
```

- [ ] **Step 4: 跑确认 pass + commit**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_scheduled_runner.py -v`
Expected: PASS(4 passed)
```bash
git add services/backend/src/agent_cloud_backend/scheduler/runner.py services/backend/tests/test_scheduled_runner.py
git commit -m "feat(sched): run_scheduled_task (new session + [SILENT] + status + receipt)"
```

---

### Task 8: 轮询器 `poll_once` + `scheduler_loop`

**Files:**
- Create: `services/backend/src/agent_cloud_backend/scheduler/poller.py`
- Test: `services/backend/tests/test_scheduler_poller.py`

- [ ] **Step 1: 写失败测试** `tests/test_scheduler_poller.py`

```python
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from agent_cloud_backend.config import Settings
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.scheduled_task import ScheduledTask
from agent_cloud_backend.models.user import User
from agent_cloud_backend.scheduler import poller as P
from sqlalchemy.ext.asyncio import async_sessionmaker


async def _seed_task(maker, **kw) -> uuid.UUID:
    async with maker() as s:
        u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
        s.add(u); await s.flush()
        a = AgentConfig(user_id=u.id, name="a", model="m", provider="p")
        s.add(a); await s.flush()
        base = dict(user_id=u.id, agent_config_id=a.id, name="t", prompt="p",
                    schedule_kind="interval", schedule_expr="600", schedule_tz="UTC")
        base.update(kw)
        t = ScheduledTask(**base)
        s.add(t); await s.flush(); await s.commit()
        return t.id


def _capture_runs(monkeypatch):
    ran: list[dict] = []
    async def _fake_run(snap, settings):
        ran.append(snap)
    monkeypatch.setattr(P, "run_scheduled_task", _fake_run)
    return ran


async def test_poll_advances_next_run_and_dispatches(engine, monkeypatch):
    import agent_cloud_backend.db as db_module
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_sessionmaker", maker)
    ran = _capture_runs(monkeypatch)
    now = datetime.now(UTC)
    tid = await _seed_task(maker, next_run_at=now - timedelta(seconds=2))

    await P.poll_once(Settings(_env_file=None))

    assert [r["id"] for r in ran] == [tid]
    async with maker() as s:
        t = await s.get(ScheduledTask, tid)
        assert t.next_run_at > now  # 已先推进(at-most-once)
        assert t.running_since is not None  # 标记在跑


async def test_poll_fast_forwards_stale_without_running(engine, monkeypatch):
    import agent_cloud_backend.db as db_module
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_sessionmaker", maker)
    ran = _capture_runs(monkeypatch)
    now = datetime.now(UTC)
    # 600s 周期、过期 5000s(远超 grace=300)→ 快进 + skipped,不执行
    tid = await _seed_task(maker, next_run_at=now - timedelta(seconds=5000))

    await P.poll_once(Settings(_env_file=None))
    assert ran == []
    async with maker() as s:
        t = await s.get(ScheduledTask, tid)
        assert t.last_status == "skipped"
        assert t.next_run_at > now


async def test_poll_once_disables_once_task(engine, monkeypatch):
    import agent_cloud_backend.db as db_module
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_sessionmaker", maker)
    _capture_runs(monkeypatch)
    now = datetime.now(UTC)
    tid = await _seed_task(maker, schedule_kind="once",
                           schedule_expr=(now - timedelta(seconds=2)).isoformat(),
                           next_run_at=now - timedelta(seconds=2))
    await P.poll_once(Settings(_env_file=None))
    async with maker() as s:
        t = await s.get(ScheduledTask, tid)
        assert t.enabled is False
        assert t.next_run_at is None


async def test_scheduler_loop_survives_poll_error(monkeypatch):
    calls = {"n": 0}
    fired = asyncio.Event()
    async def _boom(settings):
        calls["n"] += 1
        fired.set()
        raise RuntimeError("boom")
    monkeypatch.setattr(P, "poll_once", _boom)
    s = Settings(_env_file=None)
    object.__setattr__(s, "scheduler_poll_interval_seconds", 0)  # 紧循环
    task = asyncio.create_task(P.scheduler_loop(s))
    await asyncio.wait_for(fired.wait(), timeout=2)
    await asyncio.sleep(0.02)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert calls["n"] >= 2  # 抛错后仍继续
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_scheduler_poller.py -v`
Expected: FAIL(`ModuleNotFoundError: scheduler.poller`)

- [ ] **Step 3: 实现** `services/backend/src/agent_cloud_backend/scheduler/poller.py`

```python
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from agent_cloud_backend.config import Settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.repositories.scheduled_task import ScheduledTaskRepository
from agent_cloud_backend.scheduler import schedule
from agent_cloud_backend.scheduler.runner import run_scheduled_task

logger = logging.getLogger(__name__)


async def scheduler_loop(settings: Settings) -> None:
    """lifespan 后台任务:周期轮询到期定时任务。单次失败不退出循环。"""
    while True:
        try:
            await poll_once(settings)
        except Exception:
            logger.exception("scheduler poll pass failed")
        await asyncio.sleep(settings.scheduler_poll_interval_seconds)


async def poll_once(settings: Settings) -> list[dict]:
    """取到期任务 → 先推进 next_run/标记 running(同一加锁事务内)→ 提交释放行锁 → 并发跑回合。
    返回本轮实际派去执行的任务快照列表。"""
    now = datetime.now(UTC)
    to_run: list[dict] = []
    async with get_sessionmaker()() as db:
        repo = ScheduledTaskRepository(db)
        due = await repo.select_due_for_update(
            now, limit=settings.scheduler_batch_size,
            run_lease_seconds=settings.scheduler_run_lease_seconds,
        )
        for t in due:
            grace = schedule.grace_seconds(t.schedule_kind, t.schedule_expr, t.schedule_tz, t.next_run_at)
            new_next = schedule.next_run_after(
                t.schedule_kind, t.schedule_expr, t.schedule_tz, prev=t.next_run_at, now=now
            )
            stale = grace > 0 and t.next_run_at < now - timedelta(seconds=grace)
            t.next_run_at = new_next
            if new_next is None:
                t.enabled = False  # once 跑完即停
            if stale:
                t.last_status = "skipped"  # 陈旧周期任务:快进、本轮不补跑
                t.last_run_at = now
            else:
                t.running_since = now
                to_run.append({
                    "id": t.id, "user_id": t.user_id, "agent_config_id": t.agent_config_id,
                    "name": t.name, "prompt": t.prompt, "origin_session_id": t.origin_session_id,
                })
        await db.commit()  # 释放行锁(回合执行前)

    if not to_run:
        return to_run
    sem = asyncio.Semaphore(settings.scheduler_max_concurrent_runs)

    async def _guarded(snap: dict) -> None:
        async with sem:
            await run_scheduled_task(snap, settings)

    await asyncio.gather(*(_guarded(s) for s in to_run), return_exceptions=True)
    return to_run
```

- [ ] **Step 4: 跑确认 pass + commit**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_scheduler_poller.py -v`
Expected: PASS(4 passed)
```bash
git add services/backend/src/agent_cloud_backend/scheduler/poller.py services/backend/tests/test_scheduler_poller.py
git commit -m "feat(sched): poller (SKIP LOCKED, advance-before-run, fast-forward)"
```

---

### Task 9: `main.py` lifespan 接线

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/main.py`
- Test: `services/backend/tests/test_scheduler_lifespan.py`

- [ ] **Step 1: 写失败测试** `tests/test_scheduler_lifespan.py`

```python
import asyncio

import agent_cloud_backend.main as main_mod


async def test_lifespan_starts_and_cancels_scheduler(monkeypatch):
    started = asyncio.Event()

    async def fake_sched(settings):
        started.set()
        await asyncio.sleep(3600)

    async def fake_reaper(*a, **k):
        await asyncio.sleep(3600)

    monkeypatch.setattr(main_mod, "scheduler_loop", fake_sched)
    monkeypatch.setattr(main_mod, "_reaper_loop", fake_reaper)
    app = main_mod.create_app()
    async with main_mod.lifespan(app):
        await asyncio.wait_for(started.wait(), timeout=2)
    # 退出后任务已被取消(没有挂起任务泄漏)—— 不抛即视为收尾正常


async def test_lifespan_skips_scheduler_when_disabled(monkeypatch):
    called = {"n": 0}

    async def fake_sched(settings):
        called["n"] += 1

    async def fake_reaper(*a, **k):
        await asyncio.sleep(3600)

    monkeypatch.setattr(main_mod, "scheduler_loop", fake_sched)
    monkeypatch.setattr(main_mod, "_reaper_loop", fake_reaper)
    monkeypatch.setenv("AGENT_CLOUD_SCHEDULER_ENABLED", "false")
    app = main_mod.create_app()
    async with main_mod.lifespan(app):
        await asyncio.sleep(0.05)
    assert called["n"] == 0
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_scheduler_lifespan.py -v`
Expected: FAIL(`AttributeError: module ... has no attribute 'scheduler_loop'`)

- [ ] **Step 3: 接线 lifespan** —— `main.py` 顶部加 import:
```python
from agent_cloud_backend.scheduler.poller import scheduler_loop
```
把 `lifespan` 改为(在起 reaper 后、`try` 前加起 scheduler;`finally` 里一并取消):

```python
@asynccontextmanager
async def lifespan(app):
    from agent_cloud_backend.config import get_settings
    from agent_cloud_backend.sandbox.deps import get_sandbox_manager

    settings = get_settings()
    manager = get_sandbox_manager()
    task = asyncio.create_task(_reaper_loop(settings.sandbox_reap_interval_seconds, manager))
    sched_task = (
        asyncio.create_task(scheduler_loop(settings)) if settings.scheduler_enabled else None
    )
    try:
        yield
    finally:
        tasks = [t for t in (task, sched_task) if t is not None]
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        from agent_cloud_backend.turn.hub import get_turn_hub
        from agent_cloud_backend.turn.runner import drain_hub

        await drain_hub(get_turn_hub())
```

- [ ] **Step 4: 跑确认 pass + Phase 2 收口回归 + commit**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_scheduler_lifespan.py -v`
Expected: PASS(2 passed)

Run(Phase 2 整体回归):`cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q`
Expected: 全绿
```bash
git add services/backend/src/agent_cloud_backend/main.py services/backend/tests/test_scheduler_lifespan.py
git commit -m "feat(sched): start scheduler loop in lifespan (gated by scheduler_enabled)"
```

---

## Phase 3 — UI 后端(REST CRUD + mark-read)

### Task 10: schemas + `api/scheduled_tasks.py`(CRUD + run-now)+ 注册路由

**Files:**
- Create: `services/backend/src/agent_cloud_backend/schemas/scheduled_task.py`
- Create: `services/backend/src/agent_cloud_backend/api/scheduled_tasks.py`
- Modify: `services/backend/src/agent_cloud_backend/main.py`(注册 router)
- Test: `services/backend/tests/test_scheduled_tasks_api.py`

- [ ] **Step 1: 写失败测试** `tests/test_scheduled_tasks_api.py`

```python
import uuid
from datetime import UTC, datetime

import pytest
from tests.conftest import register_user


async def _make_agent(auth_client) -> str:
    r = await auth_client.post(
        "/agent-configs", json={"name": "a", "model": "m", "provider": "p"}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_create_list_scoped(auth_client):
    aid = await _make_agent(auth_client)
    r = await auth_client.post("/scheduled-tasks", json={
        "name": "每日新闻", "prompt": "总结新闻", "agent_config_id": aid,
        "schedule_kind": "cron", "schedule_expr": "0 9 * * *", "schedule_tz": "Asia/Shanghai",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "每日新闻"
    assert body["next_run_at"] is not None
    assert body["enabled"] is True

    lst = await auth_client.get("/scheduled-tasks")
    assert [t["name"] for t in lst.json()] == ["每日新闻"]


async def test_create_rejects_bad_schedule(auth_client):
    aid = await _make_agent(auth_client)
    r = await auth_client.post("/scheduled-tasks", json={
        "name": "x", "prompt": "p", "agent_config_id": aid,
        "schedule_kind": "cron", "schedule_expr": "not a cron",
    })
    assert r.status_code == 422


async def test_create_other_users_agent_404(auth_client, client):
    aid = await _make_agent(auth_client)
    other_access, _ = await register_user(client)
    r = await client.post(
        "/scheduled-tasks",
        headers={"Authorization": f"Bearer {other_access}"},
        json={"name": "x", "prompt": "p", "agent_config_id": aid,
              "schedule_kind": "interval", "schedule_expr": "600"},
    )
    assert r.status_code == 404  # agent 不属本人


async def test_patch_pause_resume_recomputes(auth_client):
    aid = await _make_agent(auth_client)
    tid = (await auth_client.post("/scheduled-tasks", json={
        "name": "t", "prompt": "p", "agent_config_id": aid,
        "schedule_kind": "interval", "schedule_expr": "3600",
    })).json()["id"]
    # 暂停
    r = await auth_client.patch(f"/scheduled-tasks/{tid}", json={"enabled": False})
    assert r.json()["enabled"] is False
    # 恢复 → 重算 next_run
    r = await auth_client.patch(f"/scheduled-tasks/{tid}", json={"enabled": True})
    assert r.json()["enabled"] is True
    assert r.json()["next_run_at"] is not None


async def test_run_now_sets_next_run_now(auth_client):
    aid = await _make_agent(auth_client)
    tid = (await auth_client.post("/scheduled-tasks", json={
        "name": "t", "prompt": "p", "agent_config_id": aid,
        "schedule_kind": "cron", "schedule_expr": "0 9 * * *",
    })).json()["id"]
    r = await auth_client.post(f"/scheduled-tasks/{tid}/run-now")
    assert r.status_code == 200
    nxt = datetime.fromisoformat(r.json()["next_run_at"])
    assert nxt <= datetime.now(UTC)  # 立刻到期,轮询器会拾取


async def test_delete_and_404(auth_client):
    aid = await _make_agent(auth_client)
    tid = (await auth_client.post("/scheduled-tasks", json={
        "name": "t", "prompt": "p", "agent_config_id": aid,
        "schedule_kind": "interval", "schedule_expr": "600",
    })).json()["id"]
    assert (await auth_client.delete(f"/scheduled-tasks/{tid}")).status_code == 204
    assert (await auth_client.patch(f"/scheduled-tasks/{tid}", json={"name": "z"})).status_code == 404
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_scheduled_tasks_api.py -v`
Expected: FAIL(404,路由不存在)

- [ ] **Step 3: 建 schemas** `services/backend/src/agent_cloud_backend/schemas/scheduled_task.py`

```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ScheduledTaskCreate(BaseModel):
    name: str
    prompt: str
    agent_config_id: uuid.UUID
    schedule_kind: str
    schedule_expr: str
    schedule_tz: str = "Asia/Shanghai"


class ScheduledTaskUpdate(BaseModel):
    name: str | None = None
    prompt: str | None = None
    schedule_kind: str | None = None
    schedule_expr: str | None = None
    schedule_tz: str | None = None
    enabled: bool | None = None


class ScheduledTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    agent_config_id: uuid.UUID
    name: str
    prompt: str
    schedule_kind: str
    schedule_expr: str
    schedule_tz: str
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_status: str | None
    last_error: str | None
    last_delivery_error: str | None
    last_run_session_id: uuid.UUID | None
    created_at: datetime
```

- [ ] **Step 4: 建路由** `services/backend/src/agent_cloud_backend/api/scheduled_tasks.py`

```python
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.api.ownership import owned_agent
from agent_cloud_backend.models.scheduled_task import ScheduledTask
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.scheduled_task import ScheduledTaskRepository
from agent_cloud_backend.scheduler import schedule
from agent_cloud_backend.scheduler.schedule import ScheduleError
from agent_cloud_backend.schemas.scheduled_task import (
    ScheduledTaskCreate,
    ScheduledTaskRead,
    ScheduledTaskUpdate,
)

router = APIRouter(prefix="/scheduled-tasks", tags=["scheduled-tasks"])


def _normalize_or_422(kind: str, expr: str, tz: str) -> str:
    try:
        return schedule.validate_and_normalize(kind, expr, tz)
    except ScheduleError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("", response_model=list[ScheduledTaskRead])
async def list_tasks(
    session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)
):
    return await ScheduledTaskRepository(session).list_by_user(user.id)


@router.post("", response_model=ScheduledTaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: ScheduledTaskCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    await owned_agent(body.agent_config_id, user.id, session)  # 不属本人 → 404
    norm = _normalize_or_422(body.schedule_kind, body.schedule_expr, body.schedule_tz)
    next_run = schedule.first_run_at(body.schedule_kind, norm, body.schedule_tz, datetime.now(UTC))
    t = ScheduledTask(
        user_id=user.id, agent_config_id=body.agent_config_id, name=body.name, prompt=body.prompt,
        schedule_kind=body.schedule_kind, schedule_expr=norm, schedule_tz=body.schedule_tz,
        next_run_at=next_run,
    )
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return t


@router.patch("/{task_id}", response_model=ScheduledTaskRead)
async def update_task(
    task_id: uuid.UUID,
    body: ScheduledTaskUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    repo = ScheduledTaskRepository(session)
    t = await repo.get_owned(task_id, user.id)
    if t is None:
        raise HTTPException(status_code=404, detail="scheduled task not found")
    data = body.model_dump(exclude_unset=True)
    schedule_changed = any(k in data for k in ("schedule_kind", "schedule_expr", "schedule_tz"))
    for k, v in data.items():
        setattr(t, k, v)
    if schedule_changed:
        t.schedule_expr = _normalize_or_422(t.schedule_kind, t.schedule_expr, t.schedule_tz)
    # 改了排期、或刚被(重新)启用 → 重算下次触发(暂停 enabled=False 时 due 查询已会跳过)
    if (schedule_changed or data.get("enabled") is True) and t.enabled:
        t.next_run_at = schedule.first_run_at(
            t.schedule_kind, t.schedule_expr, t.schedule_tz, datetime.now(UTC)
        )
    await session.commit()
    await session.refresh(t)
    return t


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    repo = ScheduledTaskRepository(session)
    t = await repo.get_owned(task_id, user.id)
    if t is None:
        raise HTTPException(status_code=404, detail="scheduled task not found")
    await repo.delete(t)
    await session.commit()


@router.post("/{task_id}/run-now", response_model=ScheduledTaskRead)
async def run_now(
    task_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    repo = ScheduledTaskRepository(session)
    t = await repo.get_owned(task_id, user.id)
    if t is None:
        raise HTTPException(status_code=404, detail="scheduled task not found")
    t.enabled = True
    t.next_run_at = datetime.now(UTC)  # 立即到期 → 轮询器 ≤1 周期内拾取(单一执行路径)
    await session.commit()
    await session.refresh(t)
    return t
```

- [ ] **Step 5: 注册 router** —— `main.py` 的 `from agent_cloud_backend.api import (...)` 加 `scheduled_tasks`,并加进 `for module in (...)` 元组。

- [ ] **Step 6: 跑确认 pass + commit**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_scheduled_tasks_api.py -v`
Expected: PASS(6 passed)
```bash
git add services/backend/src/agent_cloud_backend/schemas/scheduled_task.py services/backend/src/agent_cloud_backend/api/scheduled_tasks.py services/backend/src/agent_cloud_backend/main.py services/backend/tests/test_scheduled_tasks_api.py
git commit -m "feat(sched): REST CRUD + run-now for scheduled tasks"
```

---

### Task 11: `mark-read` 端点 + `SessionRead` 暴露 unread/scheduled_task_id

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/schemas/session.py`(`SessionRead` 加两字段)
- Modify: `services/backend/src/agent_cloud_backend/api/sessions.py`(加 `mark-read` 端点)
- Test: `services/backend/tests/test_session_mark_read.py`

- [ ] **Step 1: 写失败测试** `tests/test_session_mark_read.py`

```python
import uuid

from agent_cloud_backend.repositories.session import SessionRepository
from sqlalchemy.ext.asyncio import async_sessionmaker


async def test_list_sessions_exposes_unread_and_scheduled(auth_client):
    aid = (await auth_client.post(
        "/agent-configs", json={"name": "a", "model": "m", "provider": "p"}
    )).json()["id"]
    r = await auth_client.post("/sessions", json={"agent_config_id": aid})
    assert r.status_code == 201
    body = r.json()
    assert body["unread"] is False
    assert body["scheduled_task_id"] is None


async def test_mark_read_clears_unread(auth_client, engine):
    aid = (await auth_client.post(
        "/agent-configs", json={"name": "a", "model": "m", "provider": "p"}
    )).json()["id"]
    sid = (await auth_client.post("/sessions", json={"agent_config_id": aid})).json()["id"]
    # 直接把它标为未读(模拟定时运行产物)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await SessionRepository(s).set_unread(uuid.UUID(sid), True)
        await s.commit()
    assert (await auth_client.get("/sessions")).json()[0]["unread"] is True

    r = await auth_client.post(f"/sessions/{sid}/mark-read")
    assert r.status_code == 204
    assert (await auth_client.get("/sessions")).json()[0]["unread"] is False


async def test_mark_read_other_user_404(auth_client, client):
    from tests.conftest import register_user
    aid = (await auth_client.post(
        "/agent-configs", json={"name": "a", "model": "m", "provider": "p"}
    )).json()["id"]
    sid = (await auth_client.post("/sessions", json={"agent_config_id": aid})).json()["id"]
    other, _ = await register_user(client)
    r = await client.post(f"/sessions/{sid}/mark-read", headers={"Authorization": f"Bearer {other}"})
    assert r.status_code == 404
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_session_mark_read.py -v`
Expected: FAIL(`unread` 不在响应 / mark-read 404 路由不存在)

- [ ] **Step 3: `SessionRead` 加字段** —— `schemas/session.py` 的 `SessionRead` 末尾加:

```python
    scheduled_task_id: uuid.UUID | None = None
    unread: bool = False
```

- [ ] **Step 4: 加 mark-read 端点** —— `api/sessions.py` 末尾加(`SessionRepository` 已 import):

```python
@router.post("/{session_id}/mark-read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_session_read(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """清未读角标(GET 取消息不应有副作用 → 单独端点)。前端打开会话时调。"""
    await owned_session(session_id, user.id, session)  # 404
    await SessionRepository(session).mark_read(session_id)
    await session.commit()
```

- [ ] **Step 5: 跑确认 pass + Phase 3 收口回归 + commit**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_session_mark_read.py -v`
Expected: PASS(3 passed)

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q`
Expected: 全绿
```bash
git add services/backend/src/agent_cloud_backend/schemas/session.py services/backend/src/agent_cloud_backend/api/sessions.py services/backend/tests/test_session_mark_read.py
git commit -m "feat(sched): session mark-read endpoint + expose unread/scheduled_task_id"
```

---

## Phase 4 — agent `schedule_task` 工具(remember 模式)

### Task 12: proto `is_scheduled_run` + 串到 assemble/headless/runner(自排期护栏)

**Files:**
- Modify: `protos/agent_cloud/v1/worker.proto`(`RunTurnRequest` 加字段)
- Regenerate: `packages/common/src/agent_cloud/v1/worker_pb2*.py`(`bash scripts/gen_protos.sh`)
- Modify: `services/backend/src/agent_cloud_backend/turn/assemble.py`(加 `is_scheduled_run` 参数 + 写入 proto)
- Modify: `services/backend/src/agent_cloud_backend/turn/headless.py`(`execute_turn_headless` 加 `is_scheduled_run` 参数,串到 `_assemble`)
- Modify: `services/backend/src/agent_cloud_backend/scheduler/runner.py`(调 headless 时传 `is_scheduled_run=True`)
- Test: `services/backend/tests/test_assemble_scheduled.py`

- [ ] **Step 1: 改 proto** —— `protos/agent_cloud/v1/worker.proto` 的 `RunTurnRequest` 末尾(field 12 后)加:

```proto
  bool is_scheduled_run = 13;  // true=本回合由定时任务触发;worker 据此不暴露 schedule_task(防自排期)
```

- [ ] **Step 2: 重生成桩**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/.claude/worktrees/feat-scheduled-tasks && bash scripts/gen_protos.sh`
Expected: 打印 `generated stubs under packages/common/src/agent_cloud/v1/`(`worker_pb2.py` 含 `is_scheduled_run`)

- [ ] **Step 3: 写失败测试** `services/backend/tests/test_assemble_scheduled.py`

```python
import uuid

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.models.user import User
from agent_cloud_backend.turn.assemble import build_run_turn_request


async def _seed(session) -> Session:
    u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
    session.add(u); await session.flush()
    a = AgentConfig(user_id=u.id, name="a", model="m", provider="p")
    session.add(a); await session.flush()
    s = Session(user_id=u.id, agent_config_id=a.id, work_subdir="workspace")
    session.add(s); await session.flush()
    return s


async def test_is_scheduled_run_flag_defaults_false(session):
    s = await _seed(session)
    req = await build_run_turn_request(
        session, s, sandbox_endpoint="x", user_message="hi", exclude_message_id=None
    )
    assert req.is_scheduled_run is False


async def test_is_scheduled_run_flag_true(session):
    s = await _seed(session)
    req = await build_run_turn_request(
        session, s, sandbox_endpoint="x", user_message="hi", exclude_message_id=None,
        is_scheduled_run=True,
    )
    assert req.is_scheduled_run is True
```

- [ ] **Step 4: 跑确认 fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_assemble_scheduled.py -v`
Expected: FAIL(`build_run_turn_request() got an unexpected keyword argument 'is_scheduled_run'`)

- [ ] **Step 5: 串参数**

`assemble.py`:`build_run_turn_request` 签名加 `is_scheduled_run: bool = False`(放在 `sandbox_token` 后),并在 `worker_pb2.RunTurnRequest(...)` 里加 `is_scheduled_run=is_scheduled_run,`。

`headless.py`:`execute_turn_headless` 签名加 `is_scheduled_run: bool = False`;`_assemble()` 里 `build_run_turn_request(... work_subdir=wd, is_scheduled_run=is_scheduled_run)`。

`scheduler/runner.py`:`execute_turn_headless(session_id, f"{CRON_HINT}\n\n{snap['prompt']}", settings=settings, manager=..., store=..., is_scheduled_run=True)`。

- [ ] **Step 6: 跑确认 pass + commit**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_assemble_scheduled.py tests/test_turn_endpoint.py -v`
Expected: PASS(新 2 + 既有端点不回归)
```bash
git add protos/agent_cloud/v1/worker.proto packages/common/src/agent_cloud/v1/ services/backend/src/agent_cloud_backend/turn/assemble.py services/backend/src/agent_cloud_backend/turn/headless.py services/backend/src/agent_cloud_backend/scheduler/runner.py services/backend/tests/test_assemble_scheduled.py
git commit -m "feat(sched): is_scheduled_run flag (proto + assemble + headless + runner)"
```

---

### Task 13: worker `schedule_task` 工具(`SchedulingExecutor`)

**Files:**
- Create: `services/worker/src/agent_cloud_worker/schedule_task.py`
- Modify: `services/worker/src/agent_cloud_worker/server.py`(`_build_executor` 包一层 + import)
- Test: `services/worker/tests/test_schedule_task.py`

- [ ] **Step 1: 写失败测试** `services/worker/tests/test_schedule_task.py`

```python
from agent_cloud_common import ToolCall, ToolResult, ToolSpec
from agent_cloud_worker.schedule_task import (
    SCHEDULE_TASK_SPEC,
    SchedulingExecutor,
    schedule_task_enabled,
)


class _Inner:
    def specs(self):
        return [ToolSpec(name="bash", description="", input_schema={})]

    async def execute(self, call):
        return ToolResult(call_id=call.id, content=f"ran {call.name}", is_error=False)


def test_enabled_logic():
    assert schedule_task_enabled([]) is True
    assert schedule_task_enabled(["schedule_task"]) is True
    assert schedule_task_enabled(["bash"]) is False


def test_specs_gated():
    assert "schedule_task" in [s.name for s in SchedulingExecutor(_Inner(), enabled=True).specs()]
    assert "schedule_task" not in [s.name for s in SchedulingExecutor(_Inner(), enabled=False).specs()]
    assert "bash" in [s.name for s in SchedulingExecutor(_Inner(), enabled=True).specs()]


async def test_intercept_returns_confirmation_not_forwarded():
    ex = SchedulingExecutor(_Inner(), enabled=True)
    r = await ex.execute(ToolCall(id="1", name="schedule_task", arguments={
        "name": "晨报", "prompt": "总结", "schedule_kind": "cron", "schedule_expr": "0 8 * * *",
    }))
    assert r.is_error is False
    assert "ran schedule_task" not in r.content  # 没进内层/沙箱


async def test_non_schedule_delegates():
    ex = SchedulingExecutor(_Inner(), enabled=True)
    r = await ex.execute(ToolCall(id="2", name="bash", arguments={"command": "ls"}))
    assert r.content == "ran bash"


async def test_validates_required_fields_and_kind():
    ex = SchedulingExecutor(_Inner(), enabled=True)
    miss = await ex.execute(ToolCall(id="1", name="schedule_task", arguments={"name": "x"}))
    bad_kind = await ex.execute(ToolCall(id="2", name="schedule_task", arguments={
        "name": "x", "prompt": "p", "schedule_kind": "weekly", "schedule_expr": "x",
    }))
    assert miss.is_error
    assert bad_kind.is_error


async def test_disabled_rejects():
    ex = SchedulingExecutor(_Inner(), enabled=False)
    r = await ex.execute(ToolCall(id="1", name="schedule_task", arguments={
        "name": "x", "prompt": "p", "schedule_kind": "cron", "schedule_expr": "0 8 * * *",
    }))
    assert r.is_error is True


def test_spec_required_fields():
    assert set(SCHEDULE_TASK_SPEC.input_schema["required"]) == {
        "name", "prompt", "schedule_kind", "schedule_expr",
    }
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd services/worker && uv run pytest tests/test_schedule_task.py -v`
Expected: FAIL(`ModuleNotFoundError: schedule_task`)

- [ ] **Step 3: 实现** `services/worker/src/agent_cloud_worker/schedule_task.py`

```python
from __future__ import annotations

from agent_cloud_common import ToolCall, ToolResult, ToolSpec

from agent_cloud_worker.tools import ToolExecutor

# agent 主动排期工具(worker 原生:本地校验 + 合成确认,绝不进沙箱、不碰 DB)。tool_call/result
# 随 new_messages 流回,backend 在落库后扫到它、做权威校验并 INSERT scheduled_tasks
# (spec 2026-06-13-scheduled-tasks)。
SCHEDULE_TASK_SPEC = ToolSpec(
    name="schedule_task",
    description=(
        "Schedule a recurring or one-off task: at the scheduled time, a fresh session is "
        "created and you are re-run with the given prompt, producing a report the user can read "
        "later. Use for 'every morning summarize X', 'remind me at 3pm', 'check Y hourly'. "
        "schedule_kind: 'once' (schedule_expr = ISO8601 datetime), 'interval' (schedule_expr = "
        "seconds or like '30m'/'2h'/'1d', min 60s), or 'cron' (schedule_expr = 5-field cron, "
        "schedule_tz like 'Asia/Shanghai'). The prompt should be self-contained — the scheduled "
        "run has no memory of this conversation."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short human label for the task."},
            "prompt": {"type": "string", "description": "Self-contained instruction to run each time."},
            "schedule_kind": {"type": "string", "enum": ["once", "interval", "cron"]},
            "schedule_expr": {
                "type": "string",
                "description": "once: ISO8601; interval: seconds or 30m/2h/1d; cron: 5-field expr.",
            },
            "schedule_tz": {
                "type": "string",
                "description": "IANA tz for cron (default Asia/Shanghai).",
            },
        },
        "required": ["name", "prompt", "schedule_kind", "schedule_expr"],
    },
)

_KINDS = ("once", "interval", "cron")


def schedule_task_enabled(enabled_tools: list[str]) -> bool:
    """空 enabled_tools = 全部(含 schedule_task);否则需显式列出。"""
    return not enabled_tools or "schedule_task" in enabled_tools


class SchedulingExecutor:
    """装饰 ToolExecutor:加 worker 原生的 ``schedule_task`` 工具。本地校验 + 返回合成确认,
    **绝不转发沙箱、不碰 DB**;其余工具委托内层。真正落库由 backend 扫 new_messages 完成
    (含 enabled_tools 重校验 + 排期合法性 + 自排期护栏)。"""

    def __init__(self, inner: ToolExecutor, *, enabled: bool) -> None:
        self._inner = inner
        self._enabled = enabled

    def specs(self) -> list[ToolSpec]:
        specs = list(self._inner.specs())
        if self._enabled:
            specs.append(SCHEDULE_TASK_SPEC)
        return specs

    async def execute(self, call: ToolCall) -> ToolResult:
        if call.name != "schedule_task":
            return await self._inner.execute(call)
        if not self._enabled:
            return ToolResult(
                call_id=call.id, content="tool not enabled: schedule_task", is_error=True
            )
        args = call.arguments or {}
        name = args.get("name")
        prompt = args.get("prompt")
        kind = args.get("schedule_kind")
        expr = args.get("schedule_expr")
        if not all(isinstance(x, str) and x.strip() for x in (name, prompt, kind, expr)):
            return ToolResult(
                call_id=call.id,
                content="schedule_task: name/prompt/schedule_kind/schedule_expr are all required",
                is_error=True,
            )
        if kind not in _KINDS:
            return ToolResult(
                call_id=call.id,
                content="schedule_task: schedule_kind must be once/interval/cron",
                is_error=True,
            )
        # 合成确认;真正校验(croniter/时区/最小间隔)与落库由 backend 完成。
        return ToolResult(
            call_id=call.id, content=f"Scheduled '{name}' ({kind}).", is_error=False
        )
```

- [ ] **Step 4: 接进 `_build_executor`** —— `server.py`:import 处加
```python
from agent_cloud_worker.schedule_task import SchedulingExecutor, schedule_task_enabled
```
在 `executor = RememberingExecutor(sandbox_exec, enabled=remember_enabled(enabled_tools))` 之后加一行:
```python
        executor = SchedulingExecutor(
            executor,
            enabled=schedule_task_enabled(enabled_tools) and not request.is_scheduled_run,
        )
```
> `and not request.is_scheduled_run`:定时跑出来的回合**不暴露** schedule_task,防 agent 自我繁殖。

- [ ] **Step 5: 跑确认 pass + commit**

Run: `cd services/worker && uv run pytest tests/test_schedule_task.py -v`
Expected: PASS(7 passed)

Run(worker 整体不回归):`cd services/worker && uv run pytest -q`
Expected: 全绿
```bash
git add services/worker/src/agent_cloud_worker/schedule_task.py services/worker/src/agent_cloud_worker/server.py services/worker/tests/test_schedule_task.py
git commit -m "feat(sched): worker schedule_task tool (SchedulingExecutor, remember pattern)"
```

---

### Task 14: backend `apply_schedule_task_calls` + 统一落库后处理(补 remember 非流式缺口)

**Files:**
- Create: `services/backend/src/agent_cloud_backend/turn/schedule_apply.py`
- Create: `services/backend/src/agent_cloud_backend/turn/post_persist.py`
- Modify: `services/backend/src/agent_cloud_backend/turn/runner.py`(`_persist` 改调 `run_tool_side_effects`)
- Modify: `services/backend/src/agent_cloud_backend/turn/headless.py`(改调 `run_tool_side_effects`)
- Test: `services/backend/tests/test_schedule_apply.py`

- [ ] **Step 1: 写失败测试** `services/backend/tests/test_schedule_apply.py`

```python
import uuid

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.scheduled_task import ScheduledTask
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.scheduled_task import ScheduledTaskRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.turn.schedule_apply import apply_schedule_task_calls
from agent_cloud_common import Message as CMessage
from agent_cloud_common import Role, ToolCall, ToolResult
from sqlalchemy.ext.asyncio import async_sessionmaker


def _calls(args, *, ok=True, name="schedule_task", cid="c1"):
    assistant = CMessage(role=Role.ASSISTANT, tool_calls=[ToolCall(id=cid, name=name, arguments=args)])
    tool = CMessage(role=Role.TOOL, tool_results=[ToolResult(call_id=cid, content="ok", is_error=not ok)])
    return [assistant, tool]


async def _seed(maker, *, enabled_tools=None, scheduled=False):
    async with maker() as s:
        u = User(email=f"{uuid.uuid4()}@e.com", password_hash="x")
        s.add(u); await s.flush()
        a = AgentConfig(user_id=u.id, name="a", model="m", provider="p",
                        enabled_tools=enabled_tools or [])
        s.add(a); await s.flush()
        task_id = None
        if scheduled:
            t = ScheduledTask(user_id=u.id, agent_config_id=a.id, name="t", prompt="p",
                              schedule_kind="interval", schedule_expr="600", schedule_tz="UTC")
            s.add(t); await s.flush(); task_id = t.id
        sess = await SessionRepository(s).create_for(u.id, a.id, "c", scheduled_task_id=task_id)
        await s.commit()
        return u.id, sess.id


GOOD = {"name": "晨报", "prompt": "总结昨日", "schedule_kind": "cron", "schedule_expr": "0 8 * * *"}


async def test_inserts_row_with_origin(engine, monkeypatch):
    import agent_cloud_backend.db as db_module
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_sessionmaker", maker)
    uid, sid = await _seed(maker)
    n = await apply_schedule_task_calls(sid, _calls(GOOD))
    assert n == 1
    async with maker() as s:
        rows = await ScheduledTaskRepository(s).list_by_user(uid)
        assert len(rows) == 1
        assert rows[0].origin_session_id == sid
        assert rows[0].schedule_expr == "0 8 * * *"
        assert rows[0].next_run_at is not None


async def test_skips_error_result(engine, monkeypatch):
    import agent_cloud_backend.db as db_module
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_sessionmaker", maker)
    _, sid = await _seed(maker)
    assert await apply_schedule_task_calls(sid, _calls(GOOD, ok=False)) == 0


async def test_enforces_enabled_tools(engine, monkeypatch):
    import agent_cloud_backend.db as db_module
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_sessionmaker", maker)
    _, sid = await _seed(maker, enabled_tools=["bash"])  # 未含 schedule_task
    assert await apply_schedule_task_calls(sid, _calls(GOOD)) == 0


async def test_self_schedule_guard_blocks_scheduled_session(engine, monkeypatch):
    import agent_cloud_backend.db as db_module
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_sessionmaker", maker)
    _, sid = await _seed(maker, scheduled=True)  # 这是定时运行产物会话
    assert await apply_schedule_task_calls(sid, _calls(GOOD)) == 0


async def test_skips_invalid_schedule(engine, monkeypatch):
    import agent_cloud_backend.db as db_module
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_sessionmaker", maker)
    _, sid = await _seed(maker)
    bad = {**GOOD, "schedule_kind": "cron", "schedule_expr": "not a cron"}
    assert await apply_schedule_task_calls(sid, _calls(bad)) == 0
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_schedule_apply.py -v`
Expected: FAIL(`ModuleNotFoundError: turn.schedule_apply`)

- [ ] **Step 3: 实现** `services/backend/src/agent_cloud_backend/turn/schedule_apply.py`

```python
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.scheduled_task import ScheduledTask
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.scheduler.schedule import ScheduleError, first_run_at, validate_and_normalize

logger = logging.getLogger(__name__)


def _accepted_schedule_task_calls(new_messages) -> list:
    """worker【已接受】(tool_result 非错误)、按 call_id 去重的 schedule_task 调用。"""
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
            if c.name == "schedule_task" and c.id in ok_ids and c.id not in seen:
                seen.add(c.id)
                calls.append(c)
    return calls


async def apply_schedule_task_calls(session_id: uuid.UUID, new_messages) -> int:
    """把本回合 agent 主动 schedule_task 的调用落成 scheduled_tasks 行(spec 2026-06-13)。

    独立事务、best-effort。服务端权威校验:enabled_tools 重判 + 排期合法性 + **自排期护栏**
    (定时跑出来的会话不准再排期)。归属取自服务端会话,不取 LLM 给的。返回新建行数。
    """
    calls = _accepted_schedule_task_calls(new_messages)
    if not calls:
        return 0
    async with get_sessionmaker()() as db:
        s = await db.get(Session, session_id)
        if s is None:
            return 0
        if s.scheduled_task_id is not None:
            return 0  # 自排期护栏(纵深防御,即便 worker 漏暴露了工具)
        agent = await AgentConfigRepository(db).get(s.agent_config_id)
        enabled = list(agent.enabled_tools) if agent else []
        if enabled and "schedule_task" not in enabled:
            return 0
        now = datetime.now(UTC)
        created = 0
        for c in calls:
            args = c.arguments or {}
            name, prompt = args.get("name"), args.get("prompt")
            kind, expr = args.get("schedule_kind"), args.get("schedule_expr")
            tz = args.get("schedule_tz") or "Asia/Shanghai"
            if not all(isinstance(x, str) and x.strip() for x in (name, prompt, kind, expr)):
                continue
            try:
                norm = validate_and_normalize(kind, expr, tz)
                next_run = first_run_at(kind, norm, tz, now)
            except ScheduleError:
                logger.info("schedule_task: dropping invalid schedule from agent (%s/%s)", kind, expr)
                continue
            db.add(ScheduledTask(
                user_id=s.user_id, agent_config_id=s.agent_config_id,
                name=name.strip(), prompt=prompt.strip(),
                schedule_kind=kind, schedule_expr=norm, schedule_tz=tz,
                next_run_at=next_run, origin_session_id=session_id,
            ))
            created += 1
        await db.commit()
        return created
```

- [ ] **Step 4: 建统一后处理** `services/backend/src/agent_cloud_backend/turn/post_persist.py`

```python
from __future__ import annotations

import logging
import uuid

from agent_cloud_backend.turn.memory_extract import apply_remember_calls
from agent_cloud_backend.turn.schedule_apply import apply_schedule_task_calls

logger = logging.getLogger(__name__)


async def run_tool_side_effects(session_id: uuid.UUID, new_messages) -> None:
    """落库后处理 agent 主动工具(remember + schedule_task)的副作用。各自独立 best-effort,
    互不影响,也绝不拖垮消息持久化。流式(runner._persist)与非流式(headless)两条路径共用。"""
    for fn in (apply_remember_calls, apply_schedule_task_calls):
        try:
            await fn(session_id, new_messages)
        except Exception:
            logger.exception("%s failed for session %s", fn.__name__, session_id)
```

- [ ] **Step 5: 两条落库路径都改调它**

`turn/runner.py` `_persist`:把
```python
    try:
        await apply_remember_calls(session_id, new_messages)
    except Exception:
        logger.exception("apply_remember_calls failed for session %s", session_id)
```
换成
```python
    await run_tool_side_effects(session_id, new_messages)
```
并把 import `from agent_cloud_backend.turn.memory_extract import apply_remember_calls` 换成 `from agent_cloud_backend.turn.post_persist import run_tool_side_effects`。

`turn/headless.py`:把 Task 6 里的
```python
        try:
            await apply_remember_calls(session_id, commons)
        except Exception:
            logger.exception("apply_remember_calls failed for session %s", session_id)
```
换成
```python
        await run_tool_side_effects(session_id, commons)
```
import 同样把 `apply_remember_calls` 换成 `from agent_cloud_backend.turn.post_persist import run_tool_side_effects`。

- [ ] **Step 6: 跑确认 pass**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_schedule_apply.py -v`
Expected: PASS(5 passed)

- [ ] **Step 7: 验证 remember 非流式缺口已补**(回归 + 既有 remember 流式测试仍绿)

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q`
Expected: 全绿

- [ ] **Step 8: commit**

```bash
git add services/backend/src/agent_cloud_backend/turn/schedule_apply.py services/backend/src/agent_cloud_backend/turn/post_persist.py services/backend/src/agent_cloud_backend/turn/runner.py services/backend/src/agent_cloud_backend/turn/headless.py services/backend/tests/test_schedule_apply.py
git commit -m "feat(sched): apply_schedule_task_calls + unified post-persist side-effects (fixes remember non-stream gap)"
```

---

## Phase 5 — 前端

### Task 15: types + api client + `schedule_task` 工具开关

**Files:**
- Modify: `frontend/src/types.ts`(`Session` 加 2 字段 + `ScheduledTask`)
- Modify: `frontend/src/api/client.ts`(scheduledTasks + markSessionRead)
- Modify: `frontend/src/agentConfig.ts`(`BUILTIN_TOOLS` 加 schedule_task)
- 验证:`npm run lint`(纯类型/管线,行为测试在 Task 16/17)

- [ ] **Step 1: `types.ts`** —— `Session` 接口加 `scheduled_task_id: string | null` 与 `unread: boolean`;新增:

```ts
export interface ScheduledTask {
  id: string
  user_id: string
  agent_config_id: string
  name: string
  prompt: string
  schedule_kind: "once" | "interval" | "cron"
  schedule_expr: string
  schedule_tz: string
  enabled: boolean
  next_run_at: string | null
  last_run_at: string | null
  last_status: "ok" | "error" | "skipped" | null
  last_error: string | null
  last_delivery_error: string | null
  last_run_session_id: string | null
  created_at: string
}
```
`Session` 改为:
```ts
export interface Session { id: string; user_id: string; agent_config_id: string; title: string | null; work_subdir: string; last_active_at: string; last_context_tokens: number | null; scheduled_task_id: string | null; unread: boolean }
```

- [ ] **Step 2: `api/client.ts`** —— 顶部 import 加 `ScheduledTask`;`api` 对象里(sessions 块附近)加:

```ts
  markSessionRead: (id: string) => http<void>(`/sessions/${id}/mark-read`, { method: "POST" }),
  // ── 定时任务 ──
  listScheduledTasks: () => http<ScheduledTask[]>("/scheduled-tasks"),
  createScheduledTask: (body: {
    name: string; prompt: string; agent_config_id: string
    schedule_kind: string; schedule_expr: string; schedule_tz?: string
  }) => http<ScheduledTask>("/scheduled-tasks", { method: "POST", body: JSON.stringify(body) }),
  patchScheduledTask: (
    id: string,
    body: Partial<{ name: string; prompt: string; schedule_kind: string; schedule_expr: string; schedule_tz: string; enabled: boolean }>,
  ) => http<ScheduledTask>(`/scheduled-tasks/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteScheduledTask: (id: string) => http<void>(`/scheduled-tasks/${id}`, { method: "DELETE" }),
  runScheduledTask: (id: string) =>
    http<ScheduledTask>(`/scheduled-tasks/${id}/run-now`, { method: "POST" }),
```

- [ ] **Step 3: `agentConfig.ts`** —— `BUILTIN_TOOLS` 数组加一项(放在 `remember` 后):

```ts
  { name: "schedule_task", desc: "定时任务(让 agent 自助排期周期性运行)" },
```

- [ ] **Step 4: 验证 + commit**

Run: `cd frontend && npm run lint`
Expected: 通过(tsc -b 无错)
```bash
git add frontend/src/types.ts frontend/src/api/client.ts frontend/src/agentConfig.ts
git commit -m "feat(sched): frontend types + api client + schedule_task tool toggle"
```

---

### Task 16: `ScheduledTasksPanel` + TopBar「定时任务」入口

**Files:**
- Modify: `frontend/src/components/toggles/TogglePopover.tsx`(加可选 `width`)
- Create: `frontend/src/components/toggles/ScheduledTasksMenu.tsx`
- Modify: `frontend/src/components/TopBar.tsx`(加 chip + 弹层)
- Test: `frontend/src/components/toggles/ScheduledTasksMenu.test.tsx`

- [ ] **Step 1: `TogglePopover` 加宽度参数** —— 签名加 `width = "w-72"`,把容器 `className` 里的 `w-72` 换成模板:

```tsx
export function TogglePopover({
  anchorRef, title, onClose, children, width = "w-72",
}: {
  anchorRef: React.RefObject<HTMLElement | null>
  title: string
  onClose: () => void
  children: React.ReactNode
  width?: string
}) {
```
容器行改为:
```tsx
      className={`fixed z-30 ${width} rounded-xl border border-slate-200 bg-white p-1.5 shadow-pop`}
```

- [ ] **Step 2: 写失败测试** `frontend/src/components/toggles/ScheduledTasksMenu.test.tsx`

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../../api/client"
import { useStore } from "../../store"
import type { AgentConfig, ScheduledTask } from "../../types"
import { ScheduledTasksMenu } from "./ScheduledTasksMenu"

const agent = (over: Partial<AgentConfig> = {}): AgentConfig => ({
  id: "a1", user_id: "u1", name: "助手", model: "m", provider: "p",
  thinking_level: null, enabled_tools: [], permissions: {}, key_ref: null, ...over,
})
const task = (over: Partial<ScheduledTask> = {}): ScheduledTask => ({
  id: "t1", user_id: "u1", agent_config_id: "a1", name: "每日新闻", prompt: "总结",
  schedule_kind: "cron", schedule_expr: "0 9 * * *", schedule_tz: "Asia/Shanghai",
  enabled: true, next_run_at: "2026-06-14T01:00:00+00:00", last_run_at: null,
  last_status: null, last_error: null, last_delivery_error: null,
  last_run_session_id: null, created_at: "2026-06-13T00:00:00+00:00", ...over,
})

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

beforeEach(() => {
  useStore.setState({ userId: "u1", agentId: "a1" })
  vi.spyOn(api, "listAgents").mockResolvedValue([agent()])
})
afterEach(() => vi.restoreAllMocks())

describe("ScheduledTasksMenu", () => {
  it("列出已有任务", async () => {
    vi.spyOn(api, "listScheduledTasks").mockResolvedValue([task()])
    render(wrap(<ScheduledTasksMenu />))
    expect(await screen.findByText("每日新闻")).toBeInTheDocument()
  })

  it("空态", async () => {
    vi.spyOn(api, "listScheduledTasks").mockResolvedValue([])
    render(wrap(<ScheduledTasksMenu />))
    expect(await screen.findByText(/还没有定时任务/)).toBeInTheDocument()
  })

  it("创建任务调 createScheduledTask", async () => {
    vi.spyOn(api, "listScheduledTasks").mockResolvedValue([])
    const create = vi.spyOn(api, "createScheduledTask").mockResolvedValue(task())
    render(wrap(<ScheduledTasksMenu />))
    await screen.findByText(/还没有定时任务/)
    fireEvent.change(screen.getByLabelText("任务名"), { target: { value: "晨报" } })
    fireEvent.change(screen.getByLabelText("提示词"), { target: { value: "总结昨日" } })
    fireEvent.change(screen.getByLabelText("排期表达式"), { target: { value: "0 8 * * *" } })
    fireEvent.click(screen.getByRole("button", { name: "创建" }))
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
    expect(create.mock.calls[0][0]).toMatchObject({
      name: "晨报", prompt: "总结昨日", agent_config_id: "a1",
      schedule_kind: "cron", schedule_expr: "0 8 * * *",
    })
  })

  it("删除任务调 deleteScheduledTask", async () => {
    vi.spyOn(api, "listScheduledTasks").mockResolvedValue([task()])
    const del = vi.spyOn(api, "deleteScheduledTask").mockResolvedValue(undefined)
    render(wrap(<ScheduledTasksMenu />))
    await screen.findByText("每日新闻")
    fireEvent.click(screen.getByRole("button", { name: "删除 每日新闻" }))
    await waitFor(() => expect(del).toHaveBeenCalledWith("t1"))
  })
})
```

- [ ] **Step 3: 跑确认 fail**

Run: `cd frontend && npx vitest run src/components/toggles/ScheduledTasksMenu.test.tsx`
Expected: FAIL(找不到模块 `ScheduledTasksMenu`)

- [ ] **Step 4: 实现** `frontend/src/components/toggles/ScheduledTasksMenu.tsx`

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "../../api/client"
import { useStore } from "../../store"
import type { ScheduledTask } from "../../types"
import { Button, Input, Segmented, Switch, Textarea } from "../ui"

const KINDS = [
  { value: "cron", label: "Cron" },
  { value: "interval", label: "间隔" },
  { value: "once", label: "一次" },
] as const
const PLACEHOLDER: Record<string, string> = {
  cron: "0 9 * * *(每天 9 点)",
  interval: "3600 或 30m / 2h / 1d",
  once: "2026-06-14T09:00:00+08:00",
}

// TopBar「定时任务」弹层:列出本人任务 + 内联创建。任务归属 user,创建需选 agent(默认当前)。
export function ScheduledTasksMenu() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const qc = useQueryClient()
  const { data: tasks = [] } = useQuery({
    queryKey: ["scheduledTasks", userId],
    queryFn: () => api.listScheduledTasks(),
    enabled: !!userId,
  })
  const { data: agents = [] } = useQuery({ queryKey: ["agents", userId], queryFn: () => api.listAgents() })
  const invalidate = () => qc.invalidateQueries({ queryKey: ["scheduledTasks", userId] })

  const [name, setName] = useState("")
  const [prompt, setPrompt] = useState("")
  const [kind, setKind] = useState<string>("cron")
  const [expr, setExpr] = useState("")
  const [aid, setAid] = useState(agentId ?? "")
  const create = useMutation({
    mutationFn: () =>
      api.createScheduledTask({ name, prompt, agent_config_id: aid || agentId || agents[0]?.id || "", schedule_kind: kind, schedule_expr: expr }),
    onSuccess: () => {
      setName(""); setPrompt(""); setExpr("")
      invalidate()
    },
  })
  const patch = useMutation({
    mutationFn: (v: { id: string; enabled: boolean }) => api.patchScheduledTask(v.id, { enabled: v.enabled }),
    onSettled: invalidate,
  })
  const runNow = useMutation({ mutationFn: (id: string) => api.runScheduledTask(id), onSettled: invalidate })
  const remove = useMutation({ mutationFn: (id: string) => api.deleteScheduledTask(id), onSettled: invalidate })

  const canCreate = name.trim() && prompt.trim() && expr.trim() && (aid || agentId || agents[0])
  const statusDot = (t: ScheduledTask) =>
    t.last_status === "error" ? "⚠️" : t.last_status === "skipped" ? "⏭" : t.last_status === "ok" ? "✅" : "·"

  return (
    <div className="max-h-[70vh] overflow-auto px-1">
      <div className="space-y-1 pb-2">
        {tasks.length === 0 ? (
          <div className="px-2 py-3 text-center text-xs text-slate-400">还没有定时任务</div>
        ) : (
          tasks.map((t) => (
            <div key={t.id} className="rounded-lg px-2.5 py-1.5 hover:bg-slate-50">
              <div className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-xs font-medium text-slate-700">
                  {statusDot(t)} {t.name}
                </span>
                <Switch
                  checked={t.enabled}
                  onChange={() => patch.mutate({ id: t.id, enabled: !t.enabled })}
                  label={`启用 ${t.name}`}
                />
              </div>
              <div className="mt-0.5 flex items-center gap-2 text-[11px] text-slate-400">
                <span className="truncate">{t.schedule_kind} · {t.schedule_expr}</span>
                <button className="shrink-0 hover:text-brand-600" onClick={() => runNow.mutate(t.id)}>
                  立即运行
                </button>
                <button
                  className="shrink-0 hover:text-red-600"
                  aria-label={`删除 ${t.name}`}
                  onClick={() => remove.mutate(t.id)}
                >
                  删除
                </button>
              </div>
            </div>
          ))
        )}
      </div>
      <div className="space-y-1.5 border-t border-slate-100 pt-2">
        <Input aria-label="任务名" placeholder="任务名" value={name} onChange={(e) => setName(e.target.value)} />
        <Textarea aria-label="提示词" placeholder="每次运行执行的提示(自包含)" value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={2} />
        <Segmented options={KINDS} value={kind} onChange={setKind} />
        <Input aria-label="排期表达式" placeholder={PLACEHOLDER[kind]} value={expr} onChange={(e) => setExpr(e.target.value)} />
        <Button disabled={!canCreate || create.isPending} onClick={() => create.mutate()}>创建</Button>
      </div>
    </div>
  )
}
```
> 若 `Segmented`/`Input`/`Textarea`/`Button` 的 props 名与上面不符,以 `frontend/src/components/ui/` 实际签名为准微调(`npm run lint` 会逐个报)。`Input`/`Textarea` 需要透传 `aria-label`;若现有组件没透传,给它加 `...rest` 透传(测试按 label 选元素)。

- [ ] **Step 5: TopBar 加 chip + 弹层** —— `TopBar.tsx`:`open` 联合类型加 `"tasks"`;加 `const tasksBtn = useRef<HTMLButtonElement>(null)`;import `CalendarClock`(lucide)与 `ScheduledTasksMenu`。在「技能」chip 后加(**不 disabled**,任务是 user 级):

```tsx
      <button
        ref={tasksBtn}
        type="button"
        title="定时任务"
        aria-label="定时任务"
        onClick={() => setOpen(open === "tasks" ? null : "tasks")}
        className={CHIP_BTN}
      >
        <CalendarClock size={14} className="text-slate-400" />
        <span className="hidden sm:inline">定时</span>
      </button>
```
弹层区加:
```tsx
      {open === "tasks" && (
        <TogglePopover anchorRef={tasksBtn} title="定时任务" width="w-96" onClose={() => setOpen(null)}>
          <ScheduledTasksMenu />
        </TogglePopover>
      )}
```

- [ ] **Step 6: 跑确认 pass + lint + commit**

Run: `cd frontend && npx vitest run src/components/toggles/ScheduledTasksMenu.test.tsx && npm run lint`
Expected: PASS(4 passed)+ lint 通过
```bash
git add frontend/src/components/toggles/TogglePopover.tsx frontend/src/components/toggles/ScheduledTasksMenu.tsx frontend/src/components/TopBar.tsx frontend/src/components/toggles/ScheduledTasksMenu.test.tsx
git commit -m "feat(sched): ScheduledTasksMenu panel + TopBar entry"
```

---

### Task 17: 侧栏未读点 + 定时标 + 打开即标已读

**Files:**
- Modify: `frontend/src/components/SessionList.tsx`
- Test: `frontend/src/components/SessionList.test.tsx`(新增或追加)

- [ ] **Step 1: 写失败测试** `frontend/src/components/SessionList.test.tsx`

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { useStore } from "../store"
import type { Session } from "../types"
import { SessionList } from "./SessionList"

const sess = (over: Partial<Session> = {}): Session => ({
  id: "s1", user_id: "u1", agent_config_id: "a1", title: "晨报结果", work_subdir: "workspace",
  last_active_at: "2026-06-13T09:00:00+00:00", last_context_tokens: null,
  scheduled_task_id: "t1", unread: true, ...over,
})

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

beforeEach(() => useStore.setState({ userId: "u1", agentId: "a1", sessionId: null }))
afterEach(() => vi.restoreAllMocks())

describe("SessionList 定时任务标记", () => {
  it("定时产物会话显示定时标 + 未读点", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue([sess()])
    render(wrap(<SessionList />))
    expect(await screen.findByText("晨报结果")).toBeInTheDocument()
    expect(screen.getByLabelText("定时任务产物")).toBeInTheDocument()
    expect(screen.getByLabelText("未读")).toBeInTheDocument()
  })

  it("打开未读会话调 markSessionRead", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue([sess()])
    const mark = vi.spyOn(api, "markSessionRead").mockResolvedValue(undefined)
    render(wrap(<SessionList />))
    fireEvent.click(await screen.findByText("晨报结果"))
    await waitFor(() => expect(mark).toHaveBeenCalledWith("s1"))
  })

  it("已读普通会话不显示未读点", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue([sess({ unread: false, scheduled_task_id: null })])
    render(wrap(<SessionList />))
    await screen.findByText("晨报结果")
    expect(screen.queryByLabelText("未读")).toBeNull()
    expect(screen.queryByLabelText("定时任务产物")).toBeNull()
  })
})
```

- [ ] **Step 2: 跑确认 fail**

Run: `cd frontend && npx vitest run src/components/SessionList.test.tsx`
Expected: FAIL(无「定时任务产物」/「未读」标记)

- [ ] **Step 3: 改 SessionList** —— 顶部 import 加 `useQueryClient` 已有;加 `import { CalendarClock } from "lucide-react"`。把行内 label 按钮那段(`<button ... onClick={() => setSession(s.id)}>{label(s)}</button>`)替换为:

```tsx
                <button
                  className={`flex min-w-0 flex-1 items-center gap-1.5 px-2.5 py-2 text-left text-sm ${
                    s.id === sessionId ? "font-medium text-brand-800" : "text-slate-600"
                  }`}
                  onClick={() => {
                    setSession(s.id)
                    if (s.unread) {
                      void api.markSessionRead(s.id).then(() =>
                        qc.invalidateQueries({ queryKey: ["sessions", userId] }),
                      )
                    }
                  }}
                >
                  {s.scheduled_task_id && (
                    <CalendarClock size={13} aria-label="定时任务产物" className="shrink-0 text-slate-400" />
                  )}
                  <span className="min-w-0 flex-1 truncate">{label(s)}</span>
                  {s.unread && (
                    <span
                      aria-label="未读"
                      className="h-2 w-2 shrink-0 rounded-full bg-brand-500"
                    />
                  )}
                </button>
```

- [ ] **Step 4: 跑确认 pass + lint**

Run: `cd frontend && npx vitest run src/components/SessionList.test.tsx && npm run lint`
Expected: PASS(3 passed)+ lint 通过

- [ ] **Step 5: live-verify(preview)** —— 起预览,登录,造一个 once 任务(`run-now`),等轮询器(把 `AGENT_CLOUD_SCHEDULER_POLL_INTERVAL_SECONDS=5` 起 dev 栈)出新会话,截图侧栏未读点 + 定时标 + 面板。用 `preview_*` 工具验证,失败则改源码再验。

- [ ] **Step 6: commit**

```bash
git add frontend/src/components/SessionList.tsx frontend/src/components/SessionList.test.tsx
git commit -m "feat(sched): sidebar unread dot + scheduled badge + mark-read on open"
```

---

## Phase 6 — 收尾

### Task 18: 全量回归

- [ ] **Step 1: 后端整套**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q`
Expected: 全绿(含既有套件 —— 端点抽取/落库后处理改动不回归)

- [ ] **Step 2: 后端 lint**

Run: `cd services/backend && uv run ruff check src tests`
Expected: 无错(尤其 `api/turn.py` 抽取后无未用 import)

- [ ] **Step 3: worker 整套**

Run: `cd services/worker && uv run pytest -q`
Expected: 全绿

- [ ] **Step 4: 前端类型 + 单测**

Run: `cd frontend && npm run lint && npm test`
Expected: tsc -b 通过 + vitest 全绿

- [ ] **Step 5(可选)real-LLM 端到端**(确认定时任务真能跑出会话)—— 仅在配了 worker LLM key 时:`bash scripts/dev_up.sh` 起全栈(env 设 `AGENT_CLOUD_SCHEDULER_POLL_INTERVAL_SECONDS=5`),建一个 `run-now` 任务,≤10s 内侧栏出现带未读点的新会话且含模型输出。

### Task 19: 对抗式代码审查

- [ ] **Step 1: 起子 agent 审查全 diff**(模型 Opus 4.8)。审查重点(把以下作为 prompt 交给子 agent,diff 内联):
  - **并发/at-most-once**:`select_due_for_update` 的 SKIP LOCKED + advance-before-run 是否真能防多副本/多轮重复触发;`running_since` 租约边界;`poll_once` 在 commit 释放行锁后才跑回合(不持锁)是否成立。
  - **自排期护栏**:`is_scheduled_run`(worker 不暴露)+ `apply_schedule_task_calls` 跳过 `scheduled_task_id` 非空会话,两道是否都生效;有没有路径让定时 agent 排出新任务。
  - **信任边界**:`apply_schedule_task_calls` 是否只信服务端会话的 user_id/agent_config_id(不信 LLM)、重判 enabled_tools、排期非法即丢弃;`schedule_task` 的 prompt 来自 LLM,落库前是否够安全(它只是日后注入给同一 agent 的提示,等价于用户输入)。
  - **执行器抽取回归**:`execute_turn_headless` 与原非流式端点行为是否等价(锁获取/释放、重试/压缩、起名、truncation 提示是否丢了 —— 注意原端点无 truncation 处理而 runner 有,确认无遗漏语义);detached ORM 行作 `TurnResponse.messages` 序列化是否安全(`expire_on_commit=False`)。
  - **错误分列 / 不静默禁用**:执行错误 vs 投递错误是否真的分列;周期任务报错后 `enabled` 是否保持 True(next_run 已前移)。
  - **迁移**:互引 FK(`use_alter`)+ partial index 在 `create_all`(测试)与 alembic(生产)两条建表路径是否都成立;down 是否干净。
  - **回执**:append 到 origin 会话只在 `status=='idle'` 时做,避免与活跃回合抢 seq —— 够不够?seq 唯一约束有没有?
- [ ] **Step 2: 按审查发现逐条修复**(每条一个 commit;有真 bug 先补一个失败测试再修)。
- [ ] **Step 3: 修完再跑 Task 18 全量回归确认仍绿。**

### Task 20: 完成开发分支(PR)

- [ ] **Step 1: 用 superpowers:finishing-a-development-branch**(它会先验证测试、再给 4 选项)。选 **Push and create a Pull Request**。
- [ ] **Step 2: PR 正文**包含:Summary(定时任务:表+轮询器+无头执行器+UI+agent 工具)、设计/计划链接、Test Plan(后端 `pytest -m "not docker"` / worker `pytest` / 前端 `lint`+`test` / preview 截图)。
- [ ] **Step 3: 等 CI 绿**;合并按用户节奏(用户要求才合)。

---

## 计划自审(writing-plans self-review)

**1. Spec 覆盖**(逐节对 spec §5–§12):
- §5 数据模型 → Task 2(模型)/ Task 3(迁移)✅
- §6 轮询器(SKIP LOCKED / advance-before-run / 快进 / running 护栏)→ Task 8 + Task 4(`select_due_for_update`)✅
- §7 执行器(复用无头回合 / [SILENT] / 回执)→ Task 6(抽取)+ Task 7(run_scheduled_task)✅
- §8 投递与通知(新会话 / 面板 / 侧栏未读 / 回执)→ Task 7 + Task 10 + Task 16 + Task 17 ✅
- §9 创建面(UI CRUD + agent 工具 + 排期校验)→ Task 10 + Task 13 + Task 14 ✅
- §10 错误与安全(执行/投递分列 / 不静默禁用 / 防自排期 / 不信 worker)→ Task 7 + Task 8 + Task 12 + Task 13 + Task 14 ✅
- §11 范围(once/interval/cron;推迟 webhook/stagger 等)→ Task 1 全套;推迟项未进任务 ✅
- §12 测试 → 各 Task 内 TDD + Task 18/19 ✅

**2. Placeholder 扫描**:无 TBD/TODO;迁移 revision `b1c2d3e4f5a6`(`down_revision` 取实测 head `d5e6f7a8b9c0`,已核)。前端 ui 组件 props 一处注明「以实际签名为准微调」—— 这是对既有未读组件的现实让步,非占位(`npm run lint` 把关)。

**3. 类型/签名一致性**(对照 Shared Interface Contract):`create_for(..., *, scheduled_task_id, unread)`、`select_due_for_update(now, *, limit, run_lease_seconds)`、`set_result(task_id, *, status, last_run_session_id, error, delivery_error)`、`execute_turn_headless(session_id, user_content, *, settings, manager, store, is_scheduled_run=False)`、`apply_schedule_task_calls(session_id, new_messages)`、`run_tool_side_effects(session_id, new_messages)`、`first_run_at/next_run_after/grace_seconds` —— 全程一致,Task 间无漂移。`is_scheduled_run` 在 Task 6 不存在、Task 12 增补并串入,顺序自洽(Task 7 在 Task 12 后更新调用点)。

**4. 风险点**(留给执行/审查特别关注):① `execute_turn_headless` 抽取的行为等价(靠既有 `test_turn_endpoint`/`test_turn_e2e` 兜底,Task 6 Step 4);② 互引 FK 的 `use_alter` 在 `create_all` 测试路径必须生效,否则所有 DB 测试建表即挂(Task 2 一落地就会暴露);③ proto 改动需 `bash scripts/gen_protos.sh` 且桩要一并提交(Task 12)。

