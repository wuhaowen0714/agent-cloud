# 模型切换器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 仿 Claude Code 的模型选单——composer 左下 chip 即点即切,预设(默认 DeepSeek-V4-Pro)∪ 在用 ∪ 后端持久化的用户自定义模型;设置页同选单;创建 agent 免填模型;`/model` 共用选项源。

**Architecture:** 后端新增 `user_models` 表 + `/models` 三接口(POST 幂等、DELETE 归属 404);前端 `models.ts` 纯合并函数 + `useModelOptions` hook(预设∪在用∪自定义,react-query)+ 受控 `ModelMenu`(chip/field 两形态,自己不 patch agent);四个接入点各自决定 onChange 语义(composer 立即 patch、设置页改草稿)。

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + pytest;React19 + TS + react-query + zustand + lucide-react + vitest。

参考 spec:`docs/superpowers/specs/2026-06-10-model-switcher-design.md`

---

## 文件结构

**后端新增**:`models/user_model.py`、`repositories/user_model.py`、`schemas/user_model.py`、`api/user_models.py`(prefix `/models`)、迁移 `c3d4e5f6a7b8_user_models.py`、`tests/test_models_api.py`;**修改**:`models/__init__.py`、`api/ownership.py`(+`owned_user_model`)、`main.py`(挂 router)。

**前端新增**:`src/models.ts`(+test)、`components/model/useModelOptions.ts`、`components/model/ModelMenu.tsx`(+test);**修改**:`types.ts`、`api/client.ts`、`components/Composer.tsx`(+test)、`components/settings/AgentSettings.tsx`(+test)、`components/slash/useSlashCommands.ts`、`components/slash/commands.ts`(移除 dedupeModels)(+test)。

后端命令一律 `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest …`;前端一律在 `frontend/` 下。

---

## Task 1: 后端 `user_models` 表 + `/models` API(TDD)

**Files:**
- Create: `services/backend/tests/test_models_api.py`、`services/backend/src/agent_cloud_backend/models/user_model.py`、`services/backend/alembic/versions/c3d4e5f6a7b8_user_models.py`、`services/backend/src/agent_cloud_backend/repositories/user_model.py`、`services/backend/src/agent_cloud_backend/schemas/user_model.py`、`services/backend/src/agent_cloud_backend/api/user_models.py`
- Modify: `services/backend/src/agent_cloud_backend/models/__init__.py`、`services/backend/src/agent_cloud_backend/api/ownership.py`、`services/backend/src/agent_cloud_backend/main.py`

- [ ] **Step 1: 写失败测试**

Create `services/backend/tests/test_models_api.py`:

```python
import uuid


async def test_models_crud_idempotent_and_validation(auth_client):
    # 空列表
    r = await auth_client.get("/models")
    assert r.status_code == 200
    assert r.json() == []
    # 创建(trim)
    r = await auth_client.post("/models", json={"model": " GLM-5.1-Air "})
    assert r.status_code == 201
    row = r.json()
    assert row["model"] == "GLM-5.1-Air"
    # 重复幂等:同一行,不报错
    r2 = await auth_client.post("/models", json={"model": "GLM-5.1-Air"})
    assert r2.status_code == 201
    assert r2.json()["id"] == row["id"]
    # 列表可见(仅一条)
    assert [m["model"] for m in (await auth_client.get("/models")).json()] == ["GLM-5.1-Air"]
    # 校验:空/超长 → 422
    assert (await auth_client.post("/models", json={"model": "   "})).status_code == 422
    assert (await auth_client.post("/models", json={"model": "x" * 201})).status_code == 422
    # 删除 → 204,列表空;删不存在 → 404
    assert (await auth_client.delete(f"/models/{row['id']}")).status_code == 204
    assert (await auth_client.get("/models")).json() == []
    assert (await auth_client.delete(f"/models/{uuid.uuid4()}")).status_code == 404


async def test_models_cross_user_isolation_and_foreign_delete_404(auth_client):
    mid = (await auth_client.post("/models", json={"model": "mine"})).json()["id"]
    # 第二个用户(独立 token,按请求覆盖 Authorization)
    reg = await auth_client.post(
        "/auth/register", json={"email": f"{uuid.uuid4()}@e.com", "password": "password123"}
    )
    h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    assert (await auth_client.get("/models", headers=h)).json() == []  # 隔离
    assert (await auth_client.delete(f"/models/{mid}", headers=h)).status_code == 404  # 他人 → 404
    assert [m["model"] for m in (await auth_client.get("/models")).json()] == ["mine"]  # 原样
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_models_api.py -q`
Expected: FAIL(/models 404)。

- [ ] **Step 3: 实现**

Create `services/backend/src/agent_cloud_backend/models/user_model.py`:

```python
import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud_backend.models.base import Base, TimestampMixin, uuid_pk


class UserModel(Base, TimestampMixin):
    """用户自定义模型名(模型选单的「自定义」段;预设/在用不落库)。"""

    __tablename__ = "user_models"
    __table_args__ = (UniqueConstraint("user_id", "model", name="uq_user_models_user_model"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    model: Mapped[str] = mapped_column(nullable=False)
```

Edit `models/__init__.py`:import 区加 `from agent_cloud_backend.models.user_model import UserModel`,`__all__` 加 `"UserModel"`。

Create `services/backend/alembic/versions/c3d4e5f6a7b8_user_models.py`:

```python
"""user_models

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-06-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "user_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "model", name="uq_user_models_user_model"),
    )
    op.create_index(op.f("ix_user_models_user_id"), "user_models", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_user_models_user_id"), table_name="user_models")
    op.drop_table("user_models")
```

Create `repositories/user_model.py`:

```python
import uuid

from sqlalchemy import select

from agent_cloud_backend.models.user_model import UserModel
from agent_cloud_backend.repositories.base import BaseRepository


class UserModelRepository(BaseRepository[UserModel]):
    model = UserModel

    async def list_by_user(self, user_id: uuid.UUID) -> list[UserModel]:
        result = await self.session.execute(
            select(UserModel).where(UserModel.user_id == user_id).order_by(UserModel.created_at)
        )
        return list(result.scalars().all())

    async def get_or_create(self, user_id: uuid.UUID, model_name: str) -> UserModel:
        """幂等:同名已存在则返回已有行(顺序请求足够;并发撞 UNIQUE 由全局 409 兜底)。"""
        existing = (
            await self.session.execute(
                select(UserModel).where(
                    UserModel.user_id == user_id, UserModel.model == model_name
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        return await self.create(UserModel(user_id=user_id, model=model_name))
```

Create `schemas/user_model.py`:

```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserModelCreate(BaseModel):
    model: str


class UserModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    model: str
    created_at: datetime
```

Edit `api/ownership.py`:import 区加 `from agent_cloud_backend.models.user_model import UserModel`,文件末尾加:

```python
async def owned_user_model(model_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> UserModel:
    m = await db.get(UserModel, model_id)
    if m is None or m.user_id != user_id:
        raise HTTPException(status_code=404, detail="model not found")
    return m
```

Create `api/user_models.py`:

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.api.ownership import owned_user_model
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.user_model import UserModelRepository
from agent_cloud_backend.schemas.user_model import UserModelCreate, UserModelRead

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[UserModelRead])
async def list_models(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    return await UserModelRepository(db).list_by_user(user.id)


@router.post("", response_model=UserModelRead, status_code=status.HTTP_201_CREATED)
async def add_model(
    body: UserModelCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    name = body.model.strip()
    if not name or len(name) > 200:
        raise HTTPException(status_code=422, detail="model must be 1-200 chars")
    row = await UserModelRepository(db).get_or_create(user.id, name)
    await db.commit()
    return row


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    model_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    row = await owned_user_model(model_id, user.id, db)
    await db.delete(row)
    await db.commit()
```

Edit `main.py`:import 元组加 `user_models`(按字母序放 `turn,` 之后),`include_router` 循环元组加 `user_models`。

- [ ] **Step 4: 跑测试确认通过(含迁移测试)**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_models_api.py tests/test_migration.py -q`
Expected: 全 PASS(迁移测试验证 upgrade head 可建空库)。

- [ ] **Step 5: ruff + 提交**

```bash
cd services/backend && uv run ruff check src tests
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add services/backend
git commit -m "feat(backend): user_models table + /models API (idempotent POST, owned DELETE)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: 前端管道(types + api + models.ts 纯函数,TDD)

**Files:**
- Modify: `frontend/src/types.ts`、`frontend/src/api/client.ts`
- Create: `frontend/src/models.ts`、Test: `frontend/src/models.test.ts`

- [ ] **Step 1: 写失败测试**

Create `frontend/src/models.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { DEFAULT_MODEL, mergeModelOptions, PRESET_MODELS } from "./models"

describe("models", () => {
  it("预设含默认模型", () => {
    expect(PRESET_MODELS).toContain(DEFAULT_MODEL)
    expect(DEFAULT_MODEL).toBe("DeepSeek-V4-Pro")
  })

  it("合并顺序:预设 → 在用 → 自定义;trim 去空去重;自定义携带行", () => {
    const customs = [
      { id: "c1", model: "GLM-5.1", created_at: "" }, // 与预设重复 → 不再出现
      { id: "c2", model: "my-model", created_at: "" },
    ]
    const opts = mergeModelOptions(["gpt-x", " DeepSeek-V4-Pro ", ""], customs)
    expect(opts.map((o) => o.model)).toEqual([...PRESET_MODELS, "gpt-x", "my-model"])
    expect(opts.find((o) => o.model === "my-model")?.custom?.id).toBe("c2")
    expect(opts.find((o) => o.model === "GLM-5.1")?.custom).toBeUndefined()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/models.test.ts`
Expected: FAIL(模块不存在)。

- [ ] **Step 3: 实现**

`frontend/src/types.ts` 加(`MemoryBlock` 行后):

```ts
export interface UserModel { id: string; model: string; created_at: string }
```

`frontend/src/api/client.ts`:type import 加 `UserModel`;`clearMemory` 之后加:

```ts
  // ── 模型选单(预设之外的用户自定义模型)──
  listModels: () => http<UserModel[]>("/models"),
  addModel: (model: string) =>
    http<UserModel>("/models", { method: "POST", body: JSON.stringify({ model }) }),
  deleteModel: (id: string) => http<void>(`/models/${id}`, { method: "DELETE" }),
```

Create `frontend/src/models.ts`:

```ts
import type { UserModel } from "./types"

// 模型选单的预设(创建 agent 的默认模型取第一个语义,显式导出避免位置耦合)。
export const PRESET_MODELS = ["DeepSeek-V4-Pro", "DeepSeek-V4-Flash", "GLM-5.1"]
export const DEFAULT_MODEL = "DeepSeek-V4-Pro"

export interface ModelOption {
  model: string
  custom?: UserModel // 仅用户自定义条目携带(供删除);预设/在用没有
}

// 合并去重:预设 → 在用 → 自定义;trim、去空、保序。
export function mergeModelOptions(inUse: string[], customs: UserModel[]): ModelOption[] {
  const seen = new Set<string>()
  const out: ModelOption[] = []
  for (const m of PRESET_MODELS) {
    seen.add(m)
    out.push({ model: m })
  }
  for (const raw of inUse) {
    const m = raw?.trim()
    if (m && !seen.has(m)) {
      seen.add(m)
      out.push({ model: m })
    }
  }
  for (const c of customs) {
    const m = c.model.trim()
    if (m && !seen.has(m)) {
      seen.add(m)
      out.push({ model: m, custom: c })
    }
  }
  return out
}
```

- [ ] **Step 4: 跑测试 + tsc**

Run: `cd frontend && npx vitest run src/models.test.ts && npx tsc --noEmit`
Expected: PASS + 0 错。

- [ ] **Step 5: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/types.ts frontend/src/api/client.ts frontend/src/models.ts frontend/src/models.test.ts
git commit -m "feat(frontend): model presets + merge logic + /models api plumbing

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `useModelOptions` hook

**Files:**
- Create: `frontend/src/components/model/useModelOptions.ts`

纯装配(merge 纯函数已单测,行为由 Task 4/5 组件测试覆盖);本任务以 tsc 为准。

- [ ] **Step 1: 实现**

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "../../api/client"
import { mergeModelOptions, type ModelOption } from "../../models"
import { useStore } from "../../store"

// 模型选单的选项源:预设 ∪ 各 agent 在用 ∪ 用户自定义(后端持久化)。
// agents/userModels 都走订阅式 useQuery(与 AgentList 等共享缓存),变更即重渲染。
export function useModelOptions(): {
  options: ModelOption[]
  addModel: (model: string) => Promise<string>
  removeModel: (id: string) => Promise<void>
} {
  const userId = useStore((s) => s.userId)
  const qc = useQueryClient()
  const { data: customs = [] } = useQuery({
    queryKey: ["userModels", userId],
    queryFn: () => api.listModels(),
    enabled: !!userId,
  })
  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })
  const invalidate = () => qc.invalidateQueries({ queryKey: ["userModels", userId] })
  const add = useMutation({ mutationFn: (m: string) => api.addModel(m), onSuccess: invalidate })
  const remove = useMutation({ mutationFn: (id: string) => api.deleteModel(id), onSuccess: invalidate })
  return {
    options: mergeModelOptions(agents.map((a) => a.model), customs),
    addModel: async (m) => (await add.mutateAsync(m.trim())).model,
    removeModel: async (id) => {
      await remove.mutateAsync(id)
    },
  }
}
```

- [ ] **Step 2: tsc + 提交**

```bash
cd frontend && npx tsc --noEmit
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/model/useModelOptions.ts
git commit -m "feat(frontend): useModelOptions hook (presets ∪ in-use ∪ custom)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `ModelMenu` 组件(TDD)

**Files:**
- Create: `frontend/src/components/model/ModelMenu.tsx`、Test: `frontend/src/components/model/ModelMenu.test.tsx`

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/model/ModelMenu.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api } from "../../api/client"
import { useStore } from "../../store"
import { ModelMenu } from "./ModelMenu"

const AGENT = {
  id: "a1", user_id: "u1", name: "A", model: "gpt-x", provider: "openai",
  thinking_level: null, enabled_tools: [], permissions: {}, key_ref: null,
}

function setup(value = "DeepSeek-V4-Pro") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  useStore.setState({ userId: "u1" })
  // 只 mock fetch(不预填缓存):useQuery 挂载即取,避免「预填后被 refetch 覆盖」的 flaky。
  vi.spyOn(api, "listModels").mockResolvedValue([{ id: "m1", model: "my-model", created_at: "" }])
  vi.spyOn(api, "listAgents").mockResolvedValue([AGENT as never])
  const onChange = vi.fn()
  render(
    <QueryClientProvider client={qc}>
      <ModelMenu value={value} onChange={onChange} />
    </QueryClientProvider>,
  )
  return { onChange }
}

const openMenu = () => fireEvent.click(screen.getByRole("button", { name: /DeepSeek-V4-Pro/ }))

afterEach(() => {
  useStore.setState({ userId: null })
  vi.restoreAllMocks()
})

describe("ModelMenu", () => {
  it("列出预设+在用+自定义,勾选当前", async () => {
    setup()
    openMenu()
    expect(await screen.findByRole("option", { name: /my-model/ })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: /gpt-x/ })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: /GLM-5\.1/ })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: /DeepSeek-V4-Pro/ })).toHaveAttribute("aria-selected", "true")
  })

  it("点击选项回调 onChange 并关闭", async () => {
    const { onChange } = setup()
    openMenu()
    fireEvent.click(await screen.findByRole("option", { name: /DeepSeek-V4-Flash/ }))
    expect(onChange).toHaveBeenCalledWith("DeepSeek-V4-Flash")
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
  })

  it("添加模型:即加即选", async () => {
    const spy = vi.spyOn(api, "addModel").mockResolvedValue({ id: "m9", model: "new-m", created_at: "" })
    const { onChange } = setup()
    openMenu()
    fireEvent.click(await screen.findByText("添加模型…"))
    const input = screen.getByPlaceholderText("模型名,Enter 确认")
    fireEvent.change(input, { target: { value: " new-m " } })
    fireEvent.keyDown(input, { key: "Enter" })
    await waitFor(() => expect(spy).toHaveBeenCalledWith("new-m"))
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("new-m"))
  })

  it("自定义条目可删,删除不触发 onChange", async () => {
    const del = vi.spyOn(api, "deleteModel").mockResolvedValue(undefined)
    const { onChange } = setup()
    openMenu()
    await screen.findByRole("option", { name: /my-model/ })
    fireEvent.click(screen.getByLabelText("删除 my-model"))
    await waitFor(() => expect(del).toHaveBeenCalledWith("m1"))
    expect(onChange).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/model/ModelMenu.test.tsx`
Expected: FAIL(模块不存在)。

- [ ] **Step 3: 实现 `ModelMenu.tsx`**

```tsx
import { Check, ChevronDown, Plus, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useModelOptions } from "./useModelOptions"

// 模型选单(仿 Claude Code):受控 value/onChange;选项 = 预设 ∪ 在用 ∪ 自定义。
// 自己不 patch agent——composer 用 onChange 立即落库,设置页用它改本地草稿。
// 自定义条目 hover 可删;底部「添加模型…」即加即选。浮层范式沿用 SelectMenu。
export function ModelMenu({
  value,
  onChange,
  variant = "field",
}: {
  value: string
  onChange: (model: string) => void
  variant?: "chip" | "field"
}) {
  const { options, addModel, removeModel } = useModelOptions()
  const [open, setOpen] = useState(false)
  const [up, setUp] = useState(false)
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState("")
  const ref = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: Event) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("pointerdown", onDoc)
    return () => document.removeEventListener("pointerdown", onDoc)
  }, [open])

  const openMenu = () => {
    const r = triggerRef.current?.getBoundingClientRect()
    if (r) {
      const below = window.innerHeight - r.bottom
      setUp(below < 320 && r.top > below) // composer 贴底 → 自然向上;设置页默认向下
    }
    setAdding(false)
    setDraft("")
    setOpen(true)
  }
  const close = () => {
    setOpen(false)
    triggerRef.current?.focus()
  }
  const submitAdd = async () => {
    const m = draft.trim()
    if (!m) return
    const saved = await addModel(m)
    onChange(saved) // 添加即选中
    close()
  }

  const triggerCls =
    variant === "field"
      ? "flex w-full items-center justify-between gap-2 rounded-xl border border-slate-200 bg-slate-100/70 px-3.5 py-2.5 text-sm transition hover:border-slate-300 hover:bg-slate-50 focus-visible:outline-none focus-visible:border-brand-400 focus-visible:bg-white focus-visible:ring-4 focus-visible:ring-brand-100/70"
      : "inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"

  return (
    <div
      ref={ref}
      className={variant === "field" ? "relative" : "relative inline-block"}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.stopPropagation()
          close()
        }
      }}
    >
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => (open ? setOpen(false) : openMenu())}
        className={triggerCls}
      >
        <span
          className={
            variant === "field"
              ? "min-w-0 flex-1 truncate text-left text-slate-800"
              : "max-w-[16rem] truncate"
          }
        >
          {value}
        </span>
        <ChevronDown size={variant === "field" ? 15 : 13} className="shrink-0 text-slate-400" />
      </button>
      {open && (
        <div
          role="listbox"
          className={`absolute z-30 max-h-72 overflow-auto rounded-xl border border-slate-200 bg-white p-1.5 shadow-pop ${
            variant === "field" ? "left-0 right-0" : "left-0 w-72"
          } ${up ? "bottom-full mb-1.5" : "top-full mt-1.5"}`}
        >
          {options.map((o) => (
            <div key={o.model} className="group flex items-center">
              <button
                type="button"
                role="option"
                aria-selected={o.model === value}
                onClick={() => {
                  onChange(o.model)
                  close()
                }}
                className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm hover:bg-slate-100 focus-visible:bg-slate-100 focus-visible:outline-none"
              >
                <span className="flex w-4 shrink-0 justify-center text-brand-600">
                  {o.model === value && <Check size={14} />}
                </span>
                <span className="min-w-0 flex-1 truncate text-slate-700">{o.model}</span>
              </button>
              {o.custom && (
                <button
                  type="button"
                  aria-label={`删除 ${o.model}`}
                  onClick={() => void removeModel(o.custom!.id)}
                  className="mr-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-slate-300 opacity-0 transition hover:bg-slate-100 hover:text-slate-600 group-hover:opacity-100"
                >
                  <X size={13} />
                </button>
              )}
            </div>
          ))}
          <div className="mt-1 border-t border-slate-100 pt-1">
            {adding ? (
              <input
                autoFocus
                value={draft}
                placeholder="模型名,Enter 确认"
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault()
                    void submitAdd()
                  } else if (e.key === "Escape") {
                    e.stopPropagation() // 只退回列表,不关整个浮层
                    setAdding(false)
                    setDraft("")
                  }
                }}
                className="w-full rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100"
              />
            ) : (
              <button
                type="button"
                onClick={() => setAdding(true)}
                className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm text-slate-500 hover:bg-slate-100 hover:text-slate-700"
              >
                <Plus size={14} className="shrink-0 text-slate-400" />
                添加模型…
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: 跑测试 + tsc**

Run: `cd frontend && npx vitest run src/components/model/ModelMenu.test.tsx && npx tsc --noEmit`
Expected: 4 PASS + 0 错。

- [ ] **Step 5: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/model
git commit -m "feat(frontend): ModelMenu controlled picker (chip/field, add & delete custom)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Composer 左下模型 chip

**Files:**
- Modify: `frontend/src/components/Composer.tsx`、Test: `frontend/src/components/Composer.test.tsx`

- [ ] **Step 1: 扩展测试(失败先行)**

`Composer.test.tsx` 的 `setup()` 里(`vi.fn()` 的 `onSend` 之前)加 mock。**注意**:`listAgents` 必须返回与 `setQueryData(["agents", USER], …)` 相同的数组(抽成 `const AGENTS = […]` 两处共用)——Composer 新增的 `useQuery(["agents"])` 挂载即后台 refetch,若 mock 回 `[]` 会把预填缓存覆盖空、chip 消失:

```ts
  vi.spyOn(api, "listModels").mockResolvedValue([])
  vi.spyOn(api, "listAgents").mockResolvedValue(AGENTS as never)
```

文件末尾新增用例:

```tsx
describe("模型 chip", () => {
  it("显示当前 agent 模型,选单切换调 patchAgent", async () => {
    const spy = vi.spyOn(api, "patchAgent").mockResolvedValue({} as never)
    setup()
    const chip = screen.getByRole("button", { name: /gpt-4o/ })
    fireEvent.click(chip)
    fireEvent.click(await screen.findByRole("option", { name: /DeepSeek-V4-Flash/ }))
    expect(spy).toHaveBeenCalledWith("a1", { model: "DeepSeek-V4-Flash" })
  })
})
```

Run: `cd frontend && npx vitest run src/components/Composer.test.tsx`
Expected: 新用例 FAIL(无 chip)。

- [ ] **Step 2: 实现**

`Composer.tsx`:
1. imports 加:

```tsx
import { useQuery } from "@tanstack/react-query"
import { api } from "../api/client"
import { useStore } from "../store"
import { ModelMenu } from "./model/ModelMenu"
```

2. 组件体内(`ctx` 之后)加:

```tsx
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  // 订阅式读取(与 AgentList 共享缓存):patchAgent 失效后 chip 文本自动更新。
  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })
  const currentModel = agents.find((a) => a.id === agentId)?.model
```

3. JSX:把 `<div ref={wrapRef} className="relative mx-auto flex max-w-5xl items-end gap-2">…</div>` 包进一层 `<div className="mx-auto max-w-5xl">`,原 wrapRef div 的 className 去掉 `mx-auto max-w-5xl`(变 `relative flex items-end gap-2`),并在 wrapRef div **之后**(同在新外层内)加:

```tsx
        {agentId && currentModel && (
          <div className="mt-1.5 flex items-center">
            <ModelMenu
              variant="chip"
              value={currentModel}
              onChange={(m) => void ctx.setModel(m)}
            />
          </div>
        )}
```

- [ ] **Step 3: 跑测试 + tsc**

Run: `cd frontend && npx vitest run src/components/Composer.test.tsx && npx tsc --noEmit`
Expected: 全 PASS(含既有斜杠用例)+ 0 错。

- [ ] **Step 4: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/Composer.tsx frontend/src/components/Composer.test.tsx
git commit -m "feat(frontend): model chip in composer footer (instant switch)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: AgentSettings(编辑行换选单 + 创建免填模型)

**Files:**
- Modify: `frontend/src/components/settings/AgentSettings.tsx`、Test: `frontend/src/components/settings/AgentSettings.test.tsx`

- [ ] **Step 1: 扩展测试(失败先行)**

读现有 `AgentSettings.test.tsx`:其 api mock(`vi.mock("../../api/client", …)` 工厂)补 `listModels: vi.fn().mockResolvedValue([])`(若用 spyOn 风格则在 setup 补同名 spy);新增用例:

```tsx
it("创建表单不填模型,提交带预设 DeepSeek-V4-Pro", async () => {
  const { api } = await import("../../api/client")
  useStore.setState({ userId: "u1", agentId: null })
  render(wrap(<AgentSettings />))
  expect(screen.queryByPlaceholderText(/model/i)).not.toBeInTheDocument()
  fireEvent.change(screen.getByPlaceholderText("name"), { target: { value: "A1" } })
  fireEvent.click(screen.getByRole("button", { name: "创建" }))
  await waitFor(() =>
    expect(api.createAgent).toHaveBeenCalledWith({
      name: "A1",
      provider: "openai",
      model: "DeepSeek-V4-Pro",
    }),
  )
})
```

(`wrap`/`useStore` 沿用该测试文件现有夹具;若无 `createAgent` mock 则补 `createAgent: vi.fn().mockResolvedValue({ id: "a9" })`。)

Run: `cd frontend && npx vitest run src/components/settings/AgentSettings.test.tsx`
Expected: 新用例 FAIL(表单仍有 model 输入)。

- [ ] **Step 2: 实现**

`AgentSettings.tsx`:
1. imports 加 `import { DEFAULT_MODEL } from "../../models"` 与 `import { ModelMenu } from "../model/ModelMenu"`。
2. **创建表单**:`draft` 改 `useState({ name: "", provider: "openai" })`;`createAgent.mutationFn` 改 `() => api.createAgent({ ...draft, model: DEFAULT_MODEL })`;提交守卫改 `if (draft.name) createAgent.mutate()`;`labels` 常量与 map 改为只 `(["name", "provider"] as const)`(labels: `{ name: "名称", provider: "Provider" }`,placeholder 直接用 `k`);分组下加一行说明:

```tsx
<div className="px-3.5 py-2 text-xs text-slate-400">模型预设为 {DEFAULT_MODEL},创建后可随时切换。</div>
```

(放在 `SettingGroup` 内最后、紧跟两个输入行。)
3. **编辑表单**「模型」行:`<Input value={form.model} …/>` 整行换成:

```tsx
<SettingRow label="模型" block>
  <ModelMenu value={form.model} onChange={(m) => setForm({ ...form, model: m })} />
</SettingRow>
```

(改的是本地草稿,点保存才 patch——与其它字段一致;`invalid` 校验不变。)

- [ ] **Step 3: 跑测试 + tsc**

Run: `cd frontend && npx vitest run src/components/settings/ && npx tsc --noEmit`
Expected: 全 PASS + 0 错。

- [ ] **Step 4: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/settings/AgentSettings.tsx frontend/src/components/settings/AgentSettings.test.tsx
git commit -m "feat(frontend): agent settings use ModelMenu; creation presets DeepSeek-V4-Pro

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `/model` 建议源共用 + 移除 dedupeModels

**Files:**
- Modify: `frontend/src/components/slash/useSlashCommands.ts`、`frontend/src/components/slash/commands.ts`、`frontend/src/components/slash/commands.test.ts`、`frontend/src/components/Composer.test.tsx`

- [ ] **Step 1: 扩展测试(失败先行)**

`Composer.test.tsx` 的 `/model` 用例(「参数模式列建议」)加一行断言(在 `expect(box()).toHaveValue("/model ")` 之后):

```tsx
    expect(await screen.findByText("DeepSeek-V4-Flash")).toBeInTheDocument() // 预设进入建议
```

Run: `cd frontend && npx vitest run src/components/Composer.test.tsx`
Expected: 该用例 FAIL(建议只来自在用模型)。

- [ ] **Step 2: 实现**

1. `useSlashCommands.ts`:
   - import 行加 `import { useModelOptions } from "../model/useModelOptions"`;移除 `dedupeModels` import(`commands` 只剩 type imports)。
   - hook 体内加 `const { options } = useModelOptions()`。
   - `modelSuggestions: () => dedupeModels(agents().map((a) => a.model))` 改为 `modelSuggestions: () => options.map((o) => o.model)`。
   - 若 `agents()` 辅助仅剩 `status()` 在用则保留(status 仍读缓存)。
2. `commands.ts`:删除 `dedupeModels` 函数及其 export(`SlashContext` 等不变;`model.suggestions` 的前缀过滤逻辑不变)。
3. `commands.test.ts`:删除 `describe("dedupeModels", …)` 块及对应 import。

- [ ] **Step 3: 全前端测试 + tsc**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: 全 PASS + 0 错。

- [ ] **Step 4: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/slash frontend/src/components/Composer.test.tsx
git commit -m "feat(frontend): /model suggestions share the model options source

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: 全量回归 + 实跑验证 + 对抗审查 + 收尾

**Files:** 无(验证 + 收尾)

- [ ] **Step 1: 前端全量**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: 0 错、全绿。

- [ ] **Step 2: 后端全量**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q && uv run ruff check src tests`
Expected: 全绿(`test_get_resume_replays_active_turn` 偶发 flaky 单跑确认)、ruff 干净。

- [ ] **Step 3: 实跑验证(preview,需登录;后端有新迁移,需重启栈跑迁移)**

逐项([feedback_preview_react_inputs]:React 输入用原生 setter + input 事件):
- composer 左下 chip 显示当前模型;点开列预设(3)+ 在用 + 自定义;选中即切(设置页确认 agent.model 已变)。
- 「添加模型…」输入 → Enter → 出现在自定义段且被选中;刷新仍在(后端持久);hover 删除。
- 新建 agent:表单无模型输入,创建后 agent.model = DeepSeek-V4-Pro。
- 设置页「模型」行为同一选单;改了不保存 → 不生效;保存 → 生效。
- `/model `:建议含预设 + 自定义。
截图留证。

- [ ] **Step 4: 对抗式代码审查(Fable 5)**

按 [feedback_dev_workflow]:子 agent(`model: "fable"`)审本分支 diff(自行 `git diff main...HEAD`,只读)。重点:跨租户(owned_user_model/隔离)、POST 幂等与并发 UNIQUE、ModelMenu 状态机(添加/删除/Esc 分层/点外面)、Composer chip 与斜杠面板/通知卡的浮层互扰、设置页草稿语义未被破坏、AgentSettings 创建 payload。发现问题 controller 直接修 + 回归。

- [ ] **Step 5: 收尾**

按 superpowers:finishing-a-development-branch 给选项(PR / 合并 / 保留 / 丢弃);用户常规选 PR(CI 绿后合)。

---

## Self-Review notes

- **Spec 覆盖**:表/迁移/三接口含幂等与 404(T1)✓;预设+DEFAULT+merge(T2)✓;hook(T3)✓;ModelMenu 受控/chip-field/勾选/删自定义/添加即选(T4)✓;composer chip 立即 patch(T5)✓;设置页编辑选单+创建免填模型(T6)✓;`/model` 共源(T7)✓;测试矩阵与 spec §5 对应 ✓;YAGNI 未引入快捷键/元数据 ✓。
- **类型一致**:`ModelOption{model, custom?}`(T2 定义,T3/T4 使用);`useModelOptions` 返回签名 T3=T4/T7 调用;api `listModels/addModel/deleteModel`(T2)与 mock 名(T4/T5/T6)一致;`DEFAULT_MODEL` T2 定义、T6 使用;迁移 down_revision=a1b2c3d4e5f6(当前 head)。
- **无占位符**:T1–T5/T7 全代码;T6 Step1 因现有测试文件结构未知,给出新用例完整代码 + mock 补齐说明(执行时按实际夹具合入),非 TODO。
