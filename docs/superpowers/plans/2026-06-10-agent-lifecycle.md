# agent/会话生命周期 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 注册自动建默认 agent(main)+ 会话;一键新建 agent(Agent N,立即行内改名);agent/会话行 hover「…」菜单支持重命名与行内二次确认删除(agent 连带其会话/记忆/文档,原子守卫防删进行中会话)。

**Architecture:** 后端:注册事务内播种默认 agent+会话;新增 `PATCH/DELETE /sessions/{id}` 与 `DELETE /agent-configs/{id}`,删除用「`idle` 或租约过期才删」的原子 SQL 守卫(行锁与回合抢锁串行,无 TOCTOU)。前端:共享 `RowMenu`(… 菜单 + 二次确认状态机),AgentList 幽灵新建行 + 行内改名,SessionList 同款菜单,Sidebar 自动落位 effect,设置抽屉创建表单移除。

**Tech Stack:** FastAPI + SQLAlchemy + pytest;React19 + TS + react-query + zustand + lucide-react + vitest。

参考 spec:`docs/superpowers/specs/2026-06-10-agent-lifecycle-design.md`

---

## 文件结构

**后端修改**:`config.py`(+default_agent_model)、`api/auth.py`(注册播种)、`schemas/session.py`(+SessionUpdate)、`api/sessions.py`(+PATCH/+DELETE)、`repositories/session.py`(+delete_if_idle/+delete_idle_for_agent/+count_for_agent)、`api/agent_configs.py`(+DELETE);**新增测试**:`tests/test_lifecycle_api.py`。

**前端新增**:`components/RowMenu.tsx`(+test)、`components/AgentList.test.tsx`、`components/SessionList.test.tsx`;**修改**:`api/client.ts`、`agentConfig.ts`(+nextAgentName,+test)、`AgentList.tsx`、`SessionList.tsx`、`Sidebar.tsx`(+自动落位)、`Sidebar.test.tsx`、`settings/AgentSettings.tsx`(移除创建表单)、`settings/AgentSettings.test.tsx`。

命令:后端 `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest …`;前端 `cd frontend && npx …`。**cwd 在调用间会重置,每条命令显式 cd。**

---

## Task 1: 注册播种默认 agent + 会话(TDD)

**Files:** Modify `services/backend/src/agent_cloud_backend/config.py`、`api/auth.py`;Create `services/backend/tests/test_lifecycle_api.py`

- [ ] **Step 1: 写失败测试**

Create `services/backend/tests/test_lifecycle_api.py`:

```python
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker


async def _register(client):
    r = await client.post(
        "/auth/register", json={"email": f"{uuid.uuid4()}@e.com", "password": "password123"}
    )
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_register_seeds_default_agent_and_session(client):
    h = await _register(client)
    agents = (await client.get("/agent-configs", headers=h)).json()
    assert [a["name"] for a in agents] == ["main"]
    assert agents[0]["model"] == "DeepSeek-V4-Pro"
    assert agents[0]["provider"] == "openai"
    sessions = (await client.get("/sessions", headers=h)).json()
    assert len(sessions) == 1
    assert sessions[0]["agent_config_id"] == agents[0]["id"]


async def test_register_conflict_leaves_no_orphans(client, engine):
    email = f"{uuid.uuid4()}@e.com"
    await client.post("/auth/register", json={"email": email, "password": "password123"})
    r = await client.post("/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 409  # 重复注册
    from agent_cloud_backend.models.agent_config import AgentConfig

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        n = (await db.execute(select(func.count()).select_from(AgentConfig))).scalar_one()
    assert n == 1  # 只有第一次注册播种的那一个,409 没有残留
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_lifecycle_api.py -q`
Expected: 第一条 FAIL(agents 为空)。

- [ ] **Step 3: 实现**

`config.py` —— 在「智能体记忆」配置块之后、`compaction_threshold_for` 方法之前加:

```python
    # 注册播种:新用户自动获得的默认 agent(开箱即用;与前端 DEFAULT_MODEL 同值)。
    default_agent_model: str = "DeepSeek-V4-Pro"
```

`api/auth.py` —— import 区加:

```python
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.session import SessionRepository
```

`register` 端点,`user = await repo.create(…)` 与 `return await _issue(…)` 之间插入:

```python
    # 新用户开箱即用:默认 agent(main)+ 一条默认会话;与 user 同一事务,同生共死。
    agent = await AgentConfigRepository(db).create(
        AgentConfig(
            user_id=user.id,
            name="main",
            model=settings.default_agent_model,
            provider="openai",
        )
    )
    await SessionRepository(db).create_for(user.id, agent.id, None)
```

- [ ] **Step 4: 跑测试 + 全量扫尾**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_lifecycle_api.py -q`
Expected: 2 passed。

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q`
注册现在播种数据,**凡经 `/auth/register`(含 `auth_client` 夹具)再对 agents/sessions 列表做精确断言的存量测试可能失败**。修法(逐个):断言从「精确等于我创建的」改为「包含我创建的」(按本测试创建的 id/name 过滤后断言),或把期望数量 +1(注明 `# +1: 注册播种的 main`)。`test_get_resume_replays_active_turn` 偶发 flaky 与此无关,单跑确认即可。
Expected: 全绿。

- [ ] **Step 5: ruff + 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run ruff check src tests
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend && git commit -m "feat(backend): registration seeds a default 'main' agent + session

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `PATCH /sessions/{id}`(重命名,TDD)

**Files:** Modify `schemas/session.py`、`api/sessions.py`;Test: `tests/test_lifecycle_api.py`

- [ ] **Step 1: 追加失败测试**

`tests/test_lifecycle_api.py` 末尾追加:

```python
async def _first_session(client, h):
    return (await client.get("/sessions", headers=h)).json()[0]


async def test_rename_session(client):
    h = await _register(client)
    sid = (await _first_session(client, h))["id"]
    r = await client.patch(f"/sessions/{sid}", json={"title": "  我的会话  "}, headers=h)
    assert r.status_code == 200
    assert r.json()["title"] == "我的会话"  # trim
    # 校验:空/超长 → 422
    assert (await client.patch(f"/sessions/{sid}", json={"title": "   "}, headers=h)).status_code == 422
    assert (await client.patch(f"/sessions/{sid}", json={"title": "x" * 201}, headers=h)).status_code == 422
    # 他人 → 404
    h2 = await _register(client)
    assert (await client.patch(f"/sessions/{sid}", json={"title": "hack"}, headers=h2)).status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_lifecycle_api.py::test_rename_session -q`
Expected: FAIL(405/404)。

- [ ] **Step 3: 实现**

`schemas/session.py` 追加:

```python
class SessionUpdate(BaseModel):
    title: str
```

`api/sessions.py`:import 行的 `from agent_cloud_backend.schemas.session import SessionCreate, SessionRead` 改为 `…import SessionCreate, SessionRead, SessionUpdate`;`list_sessions` 之后加:

```python
@router.patch("/{session_id}", response_model=SessionRead)
async def rename_session(
    session_id: uuid.UUID,
    body: SessionUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    s = await owned_session(session_id, user.id, session)  # 404
    title = body.title.strip()
    if not title or len(title) > 200:
        raise HTTPException(status_code=422, detail="title must be 1-200 chars")
    s.title = title
    await session.commit()
    await session.refresh(s)
    return s
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_lifecycle_api.py -q`
Expected: 全 PASS。

- [ ] **Step 5: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend && git commit -m "feat(backend): PATCH /sessions/{id} renames a session

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `DELETE /sessions/{id}`(原子守卫,TDD)

**Files:** Modify `repositories/session.py`、`api/sessions.py`;Test: `tests/test_lifecycle_api.py`

- [ ] **Step 1: 追加失败测试**

```python
async def test_delete_session_idle_and_guards(client, engine):
    from agent_cloud_backend.models.session import Session as SessionModel

    h = await _register(client)
    sid = (await _first_session(client, h))["id"]
    maker = async_sessionmaker(engine, expire_on_commit=False)

    # running(租约内)→ 409
    async with maker() as db:
        await db.execute(
            update(SessionModel)
            .where(SessionModel.id == uuid.UUID(sid))
            .values(status="running", last_active_at=func.now())
        )
        await db.commit()
    assert (await client.delete(f"/sessions/{sid}", headers=h)).status_code == 409

    # 回到 idle → 204,列表消失
    async with maker() as db:
        await db.execute(
            update(SessionModel).where(SessionModel.id == uuid.UUID(sid)).values(status="idle")
        )
        await db.commit()
    assert (await client.delete(f"/sessions/{sid}", headers=h)).status_code == 204
    assert (await client.get("/sessions", headers=h)).json() == []
    # 再删 → 404(已不存在);他人删 → 404(用新用户自己的会话验证)
    assert (await client.delete(f"/sessions/{sid}", headers=h)).status_code == 404
    h2 = await _register(client)
    sid2 = (await _first_session(client, h2))["id"]
    assert (await client.delete(f"/sessions/{sid2}", headers=h)).status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_lifecycle_api.py::test_delete_session_idle_and_guards -q`
Expected: FAIL(405)。

- [ ] **Step 3: 实现**

`repositories/session.py`:`from sqlalchemy import func, or_, select, update` 改为 `…import delete, func, or_, select, update`;类末尾加:

```python
    async def delete_if_idle(self, session_id: uuid.UUID, lease_seconds: int = 600) -> bool:
        """原子删除:仅 idle 或租约过期(crash 残留)才删;在跑的回合靠行锁与
        try_acquire 串行,不存在「检查后被开跑再删」的 TOCTOU。返回是否删了。"""
        cutoff = datetime.now(UTC) - timedelta(seconds=lease_seconds)
        result = await self.session.execute(
            delete(Session).where(
                Session.id == session_id,
                or_(Session.status == "idle", Session.last_active_at < cutoff),
            )
        )
        return result.rowcount == 1

    async def delete_idle_for_agent(self, agent_id: uuid.UUID, lease_seconds: int = 600) -> None:
        """删除该 agent 的全部可删会话(同上守卫);留下的(在跑)由调用方数出并 409。"""
        cutoff = datetime.now(UTC) - timedelta(seconds=lease_seconds)
        await self.session.execute(
            delete(Session).where(
                Session.agent_config_id == agent_id,
                or_(Session.status == "idle", Session.last_active_at < cutoff),
            )
        )

    async def count_for_agent(self, agent_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Session).where(Session.agent_config_id == agent_id)
        )
        return int(result.scalar_one())
```

`api/sessions.py` 追加:

```python
@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    await owned_session(session_id, user.id, session)  # 404
    if not await SessionRepository(session).delete_if_idle(session_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="session busy")
    await session.commit()  # messages 由 FK CASCADE 连带删除
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_lifecycle_api.py -q`
Expected: 全 PASS。

- [ ] **Step 5: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend && git commit -m "feat(backend): DELETE /sessions/{id} with lease-aware atomic guard

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `DELETE /agent-configs/{id}`(连带,TDD)

**Files:** Modify `api/agent_configs.py`;Test: `tests/test_lifecycle_api.py`

- [ ] **Step 1: 追加失败测试**

```python
async def test_delete_agent_cascades_and_busy_guard(client, engine):
    from agent_cloud_backend.models.context_document import ContextDocument
    from agent_cloud_backend.models.memory_entry import MemoryEntry
    from agent_cloud_backend.models.session import Session as SessionModel

    h = await _register(client)
    agent = (await client.get("/agent-configs", headers=h)).json()[0]
    aid = agent["id"]
    sid = (await _first_session(client, h))["id"]
    # 播种 agent 级记忆 + 指令文档(无 FK,验证连带清理)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        db.add(MemoryEntry(scope="agent", owner_id=uuid.UUID(aid), content="m", version=1))
        db.add(
            ContextDocument(
                scope="agent", type="AGENTS", owner_id=uuid.UUID(aid), content="doc"
            )
        )
        await db.commit()

    # 任一会话 running → 409,整体回滚(会话仍在)
    async with maker() as db:
        await db.execute(
            update(SessionModel)
            .where(SessionModel.id == uuid.UUID(sid))
            .values(status="running", last_active_at=func.now())
        )
        await db.commit()
    assert (await client.delete(f"/agent-configs/{aid}", headers=h)).status_code == 409
    assert len((await client.get("/sessions", headers=h)).json()) == 1  # 没被偷删

    # idle → 204:会话/记忆/文档全清
    async with maker() as db:
        await db.execute(
            update(SessionModel).where(SessionModel.id == uuid.UUID(sid)).values(status="idle")
        )
        await db.commit()
    assert (await client.delete(f"/agent-configs/{aid}", headers=h)).status_code == 204
    assert (await client.get("/agent-configs", headers=h)).json() == []
    assert (await client.get("/sessions", headers=h)).json() == []
    async with maker() as db:
        m = (await db.execute(select(func.count()).select_from(MemoryEntry))).scalar_one()
        d = (await db.execute(select(func.count()).select_from(ContextDocument))).scalar_one()
    assert m == 0 and d == 0
    # 他人 → 404
    h2 = await _register(client)
    aid2 = (await client.get("/agent-configs", headers=h2)).json()[0]["id"]
    assert (await client.delete(f"/agent-configs/{aid2}", headers=h)).status_code == 404
```

> `MemoryEntry`/`ContextDocument` 构造字段以模型定义为准(执行时打开两文件核对必填列;`MemoryEntry` 需要 `version`,`ContextDocument` 需要 `type`)。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_lifecycle_api.py::test_delete_agent_cascades_and_busy_guard -q`
Expected: FAIL(405)。

- [ ] **Step 3: 实现**

`api/agent_configs.py`:import 区追加:

```python
from sqlalchemy import delete as sql_delete

from agent_cloud_backend.models.context_document import ContextDocument
from agent_cloud_backend.models.memory_entry import MemoryEntry
from agent_cloud_backend.repositories.session import SessionRepository
```

文件末尾追加:

```python
@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_config(
    agent_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """删除 agent 并连带其全部会话(消息 CASCADE)、agent 级记忆与指令文档。

    任一会话仍在跑(原子守卫删不掉)→ 409 并整体回滚(get_session 依赖丢弃未提交事务);
    agent_skill_enables 由 FK CASCADE 自动清。"""
    agent = await owned_agent(agent_id, user.id, session)  # 404
    srepo = SessionRepository(session)
    await srepo.delete_idle_for_agent(agent_id)
    if await srepo.count_for_agent(agent_id) > 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="agent busy")
    await session.execute(
        sql_delete(MemoryEntry).where(
            MemoryEntry.scope == "agent", MemoryEntry.owner_id == agent_id
        )
    )
    await session.execute(
        sql_delete(ContextDocument).where(
            ContextDocument.scope == "agent", ContextDocument.owner_id == agent_id
        )
    )
    await session.delete(agent)
    await session.commit()
```

- [ ] **Step 4: 跑全部生命周期测试 + ruff**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_lifecycle_api.py -q && uv run ruff check src tests`
Expected: 全 PASS + 干净。

- [ ] **Step 5: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend && git commit -m "feat(backend): DELETE /agent-configs/{id} cascades sessions + agent-scope data

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 前端管道(api + nextAgentName,TDD)

**Files:** Modify `frontend/src/api/client.ts`、`frontend/src/agentConfig.ts`;Test: `frontend/src/agentConfig.test.ts`(已有则追加,没有则创建)

- [ ] **Step 1: 写失败测试**

`frontend/src/agentConfig.test.ts`(若不存在则创建,存在则追加 describe):

```ts
import { describe, expect, it } from "vitest"
import { nextAgentName } from "./agentConfig"

describe("nextAgentName", () => {
  it("空表 → Agent 1", () => {
    expect(nextAgentName([])).toBe("Agent 1")
  })
  it("取 Agent k 最大值 +1,忽略非模式名", () => {
    expect(nextAgentName(["main", "Agent 2", "Agent 9", "agentx"])).toBe("Agent 10")
  })
})
```

Run: `cd frontend && npx vitest run src/agentConfig.test.ts`
Expected: FAIL(函数不存在)。

- [ ] **Step 2: 实现**

`frontend/src/agentConfig.ts` 末尾追加:

```ts
// 一键新建 agent 的默认名:现有「Agent k」最大 k+1(无则 1);其它名字(main 等)不参与。
export function nextAgentName(existing: string[]): string {
  let max = 0
  for (const n of existing) {
    const m = /^Agent (\d+)$/.exec(n.trim())
    if (m) max = Math.max(max, Number(m[1]))
  }
  return `Agent ${max + 1}`
}
```

`frontend/src/api/client.ts`:`compactSession` 之后追加:

```ts
  patchSession: (id: string, body: { title: string }) =>
    http<Session>(`/sessions/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteSession: (id: string) => http<void>(`/sessions/${id}`, { method: "DELETE" }),
  deleteAgent: (id: string) => http<void>(`/agent-configs/${id}`, { method: "DELETE" }),
```

- [ ] **Step 3: 测试 + tsc + 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && npx vitest run src/agentConfig.test.ts && npx tsc --noEmit
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add frontend/src/agentConfig.ts frontend/src/agentConfig.test.ts frontend/src/api/client.ts && git commit -m "feat(frontend): lifecycle api calls + nextAgentName

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `RowMenu` 组件(TDD)

**Files:** Create `frontend/src/components/RowMenu.tsx`;Test: `frontend/src/components/RowMenu.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { RowMenu } from "./RowMenu"

const open = () => fireEvent.click(screen.getByRole("button", { name: "更多操作" }))

describe("RowMenu", () => {
  it("普通项点击即执行并关闭", async () => {
    const onSelect = vi.fn()
    render(<RowMenu ariaLabel="更多操作" items={[{ label: "重命名", onSelect }]} />)
    open()
    fireEvent.click(screen.getByRole("menuitem", { name: "重命名" }))
    await waitFor(() => expect(onSelect).toHaveBeenCalled())
    expect(screen.queryByRole("menu")).not.toBeInTheDocument()
  })

  it("带确认项需点两次:第一次变确认文案且不执行", async () => {
    const onSelect = vi.fn()
    render(
      <RowMenu
        ariaLabel="更多操作"
        items={[{ label: "删除", danger: true, confirmLabel: "确认删除?", onSelect }]}
      />,
    )
    open()
    fireEvent.click(screen.getByRole("menuitem", { name: "删除" }))
    expect(onSelect).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole("menuitem", { name: "确认删除?" }))
    await waitFor(() => expect(onSelect).toHaveBeenCalled())
  })

  it("onSelect 拒绝 → 原位提示「进行中,无法删除」", async () => {
    const onSelect = vi.fn().mockRejectedValue(new Error("409"))
    render(
      <RowMenu
        ariaLabel="更多操作"
        items={[{ label: "删除", danger: true, confirmLabel: "确认删除?", onSelect }]}
      />,
    )
    open()
    fireEvent.click(screen.getByRole("menuitem", { name: "删除" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "确认删除?" }))
    expect(await screen.findByText("进行中,无法删除")).toBeInTheDocument()
  })
})
```

Run: `cd frontend && npx vitest run src/components/RowMenu.test.tsx` → FAIL(模块不存在)。

- [ ] **Step 2: 实现 `RowMenu.tsx`**

```tsx
import { MoreHorizontal } from "lucide-react"
import { useEffect, useRef, useState } from "react"

export interface RowMenuItem {
  label: string
  danger?: boolean
  confirmLabel?: string // 有值 → 行内二次确认:第一次点击变此文案,再点才执行
  onSelect: () => void | Promise<void>
}

// 侧栏行尾「…」菜单:hover/选中显形;onSelect 抛错(如删除撞 409)原位短提示后复位。
export function RowMenu({
  items,
  ariaLabel,
  visible = false,
}: {
  items: RowMenuItem[]
  ariaLabel: string
  visible?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [confirming, setConfirming] = useState<number | null>(null)
  const [failed, setFailed] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const close = () => {
    setOpen(false)
    setConfirming(null)
    setFailed(false)
  }

  useEffect(() => {
    if (!open) return
    const onDoc = (e: Event) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close()
    }
    document.addEventListener("pointerdown", onDoc)
    return () => document.removeEventListener("pointerdown", onDoc)
  }, [open])

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  const run = async (i: number) => {
    const it = items[i]
    if (it.confirmLabel && confirming !== i) {
      setConfirming(i)
      return
    }
    try {
      await it.onSelect()
      close()
    } catch {
      setFailed(true)
      timer.current = setTimeout(close, 2000)
    }
  }

  return (
    <div
      ref={ref}
      className="relative"
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.stopPropagation()
          close()
        }
      }}
    >
      <button
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => (open ? close() : setOpen(true))}
        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-slate-400 transition hover:bg-white hover:text-slate-700 ${
          visible || open ? "opacity-100" : "opacity-0 group-hover:opacity-100"
        }`}
      >
        <MoreHorizontal size={14} />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-30 mt-1 w-44 rounded-xl border border-slate-200 bg-white p-1 shadow-pop"
        >
          {failed ? (
            <div className="px-2.5 py-1.5 text-xs text-red-600">进行中,无法删除</div>
          ) : (
            items.map((it, i) => (
              <button
                key={it.label}
                type="button"
                role="menuitem"
                onClick={() => void run(i)}
                className={`flex w-full items-center rounded-lg px-2.5 py-1.5 text-left text-sm ${
                  confirming === i
                    ? "bg-red-50 font-medium text-red-700"
                    : it.danger
                      ? "text-red-600 hover:bg-red-50"
                      : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {confirming === i ? it.confirmLabel : it.label}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: 测试 + tsc + 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && npx vitest run src/components/RowMenu.test.tsx && npx tsc --noEmit
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add frontend/src/components/RowMenu.tsx frontend/src/components/RowMenu.test.tsx && git commit -m "feat(frontend): RowMenu (hover ... menu with inline two-step confirm)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: AgentList(一键新建 + 行内改名 + 菜单,TDD)

**Files:** Modify `frontend/src/components/AgentList.tsx`;Create `frontend/src/components/AgentList.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { useStore } from "../store"
import { AgentList } from "./AgentList"

const A1 = { id: "a1", user_id: "u1", name: "main", model: "DeepSeek-V4-Pro", provider: "openai", thinking_level: null, enabled_tools: [], permissions: {}, key_ref: null }

let agents: (typeof A1)[]
const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

beforeEach(() => {
  agents = [A1]
  useStore.setState({ userId: "u1", agentId: "a1", sessionId: null })
  vi.spyOn(api, "listAgents").mockImplementation(() => Promise.resolve([...agents] as never))
})
afterEach(() => {
  useStore.setState({ userId: null, agentId: null })
  vi.restoreAllMocks()
})

describe("AgentList 一键新建", () => {
  it("默认名/默认模型直创,成功后选中并进入改名态;Enter 提交改名", async () => {
    const created = { ...A1, id: "a9", name: "Agent 1" }
    vi.spyOn(api, "createAgent").mockImplementation(() => {
      agents = [...agents, created]
      return Promise.resolve(created as never)
    })
    const patch = vi.spyOn(api, "patchAgent").mockResolvedValue(created as never)
    render(wrap(<AgentList />))
    fireEvent.click(await screen.findByRole("button", { name: "新建 Agent" }))
    await waitFor(() =>
      expect(api.createAgent).toHaveBeenCalledWith({
        name: "Agent 1",
        model: "DeepSeek-V4-Pro",
        provider: "openai",
      }),
    )
    const input = await screen.findByDisplayValue("Agent 1") // 改名态
    expect(useStore.getState().agentId).toBe("a9")
    fireEvent.change(input, { target: { value: "我的 Agent" } })
    fireEvent.keyDown(input, { key: "Enter" })
    await waitFor(() => expect(patch).toHaveBeenCalledWith("a9", { name: "我的 Agent" }))
  })
})

describe("AgentList 菜单", () => {
  it("重命名菜单项进入改名态", async () => {
    render(wrap(<AgentList />))
    await screen.findByText("main")
    fireEvent.click(screen.getByRole("button", { name: "main 更多操作" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "重命名" }))
    expect(await screen.findByDisplayValue("main")).toBeInTheDocument()
  })

  it("删除两次点击,删当前选中则落位到剩余第一个", async () => {
    const A2 = { ...A1, id: "a2", name: "second" }
    agents = [A1, A2]
    const del = vi.spyOn(api, "deleteAgent").mockImplementation(() => {
      agents = agents.filter((a) => a.id !== "a1")
      return Promise.resolve()
    })
    render(wrap(<AgentList />))
    await screen.findByText("main")
    fireEvent.click(screen.getByRole("button", { name: "main 更多操作" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "删除" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "连同全部会话删除?" }))
    await waitFor(() => expect(del).toHaveBeenCalledWith("a1"))
    await waitFor(() => expect(useStore.getState().agentId).toBe("a2"))
  })
})
```

Run: `cd frontend && npx vitest run src/components/AgentList.test.tsx` → FAIL。

- [ ] **Step 2: 重写 `AgentList.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, Settings2 } from "lucide-react"
import { useState } from "react"
import { nextAgentName } from "../agentConfig"
import { api } from "../api/client"
import { DEFAULT_MODEL } from "../models"
import { useStore } from "../store"
import { RowMenu } from "./RowMenu"

/**
 * 侧栏 agent 列表:一等导航项,点选切换。底部幽灵行一键新建(默认名 Agent N,
 * 成功即选中并进入行内改名态);行尾 hover:⚙ 设置 + … 菜单(重命名/二次确认删除,
 * 删除连带该 agent 的全部会话,由后端保证)。
 */
export function AgentList() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const setAgent = useStore((s) => s.setAgent)
  const openSettings = useStore((s) => s.openSettings)
  const qc = useQueryClient()
  const [renamingId, setRenamingId] = useState<string | null>(null)

  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ["agents", userId] })

  const create = useMutation({
    mutationFn: () =>
      api.createAgent({
        name: nextAgentName(agents.map((a) => a.name)),
        model: DEFAULT_MODEL,
        provider: "openai",
      }),
    onSuccess: async (a) => {
      await invalidate()
      setAgent(a.id)
      setRenamingId(a.id) // 新建即改名:想改顺手改,不想改 Esc 留默认名
    },
  })

  const commitRename = async (id: string, value: string, original: string) => {
    const name = value.trim()
    setRenamingId(null)
    if (!name || name === original) return
    await api.patchAgent(id, { name })
    await invalidate()
  }

  const removeAgent = async (id: string) => {
    await api.deleteAgent(id) // 409 → 抛 HttpError,由 RowMenu 原位提示
    await invalidate()
    await qc.invalidateQueries({ queryKey: ["sessions", userId] })
    if (useStore.getState().agentId === id) {
      const rest = agents.filter((a) => a.id !== id)
      setAgent(rest[0]?.id ?? null)
    }
  }

  return (
    <div className="flex flex-col">
      <div className="mb-1 px-1 text-xs font-medium tracking-wide text-slate-400">Agents</div>

      <ul className="max-h-52 space-y-0.5 overflow-auto">
        {agents.map((a) => {
          const active = a.id === agentId
          return (
            <li
              key={a.id}
              className={`group flex items-center gap-1 rounded-lg pr-1 transition ${
                active ? "bg-brand-50" : "hover:bg-slate-100"
              }`}
            >
              {renamingId === a.id ? (
                <input
                  autoFocus
                  defaultValue={a.name}
                  aria-label={`重命名 ${a.name}`}
                  onFocus={(e) => e.target.select()}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void commitRename(a.id, e.currentTarget.value, a.name)
                    else if (e.key === "Escape") setRenamingId(null)
                  }}
                  onBlur={() => setRenamingId(null)}
                  className="mx-1 my-1 w-full rounded-lg border border-brand-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
                />
              ) : (
                <>
                  <button
                    className="flex min-w-0 flex-1 items-center px-2.5 py-2 text-left"
                    onClick={() => setAgent(a.id)}
                  >
                    <span className="min-w-0 flex-1 truncate">
                      <span
                        className={`text-sm font-medium ${active ? "text-brand-800" : "text-slate-700"}`}
                      >
                        {a.name}
                      </span>
                      <span className="ml-1.5 text-xs text-slate-400">{a.model}</span>
                    </span>
                  </button>
                  <button
                    className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-slate-400 transition hover:bg-white hover:text-slate-700 ${
                      active ? "opacity-100" : "opacity-0 group-hover:opacity-100"
                    }`}
                    title="agent 设置"
                    aria-label={`${a.name} 设置`}
                    onClick={() => {
                      setAgent(a.id)
                      openSettings()
                    }}
                  >
                    <Settings2 size={14} />
                  </button>
                  <RowMenu
                    ariaLabel={`${a.name} 更多操作`}
                    visible={active}
                    items={[
                      { label: "重命名", onSelect: () => setRenamingId(a.id) },
                      {
                        label: "删除",
                        danger: true,
                        confirmLabel: "连同全部会话删除?",
                        onSelect: () => removeAgent(a.id),
                      },
                    ]}
                  />
                </>
              )}
            </li>
          )
        })}
      </ul>

      <button
        disabled={create.isPending}
        onClick={() => create.mutate()}
        className="mt-1 flex w-full items-center gap-2 rounded-xl border border-slate-200 px-3 py-1.5 text-sm text-slate-500 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700 disabled:opacity-50"
      >
        <Plus size={15} className="text-slate-400" />
        新建 Agent
      </button>
    </div>
  )
}
```

(分节头小「＋」与空态按钮被底部幽灵行取代;空表时列表为空、幽灵行仍在。)

- [ ] **Step 3: 测试 + tsc + 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && npx vitest run src/components/AgentList.test.tsx src/components/Sidebar.test.tsx && npx tsc --noEmit
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add frontend/src/components/AgentList.tsx frontend/src/components/AgentList.test.tsx && git commit -m "feat(frontend): one-click agent creation + inline rename + row menu

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: SessionList(菜单 + 改名 + 删除,TDD)

**Files:** Modify `frontend/src/components/SessionList.tsx`;Create `frontend/src/components/SessionList.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { useStore } from "../store"
import { SessionList } from "./SessionList"

const A1 = { id: "a1", user_id: "u1", name: "main", model: "m", provider: "p", thinking_level: null, enabled_tools: [], permissions: {}, key_ref: null }
const S1 = { id: "s1", user_id: "u1", agent_config_id: "a1", title: "标题一", work_subdir: "workspace", last_context_tokens: null }

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

beforeEach(() => {
  useStore.setState({ userId: "u1", agentId: "a1", sessionId: "s1" })
  vi.spyOn(api, "listAgents").mockResolvedValue([A1] as never)
  vi.spyOn(api, "listSessions").mockResolvedValue([S1] as never)
})
afterEach(() => {
  useStore.setState({ userId: null, agentId: null, sessionId: null })
  vi.restoreAllMocks()
})

describe("SessionList", () => {
  it("重命名:菜单 → input → Enter 调 patchSession", async () => {
    const patch = vi.spyOn(api, "patchSession").mockResolvedValue(S1 as never)
    render(wrap(<SessionList />))
    await screen.findByText("标题一")
    fireEvent.click(screen.getByRole("button", { name: "标题一 更多操作" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "重命名" }))
    const input = await screen.findByDisplayValue("标题一")
    fireEvent.change(input, { target: { value: "新标题" } })
    fireEvent.keyDown(input, { key: "Enter" })
    await waitFor(() => expect(patch).toHaveBeenCalledWith("s1", { title: "新标题" }))
  })

  it("删除两次点击调 deleteSession,清掉当前选中", async () => {
    const del = vi.spyOn(api, "deleteSession").mockResolvedValue(undefined)
    render(wrap(<SessionList />))
    await screen.findByText("标题一")
    fireEvent.click(screen.getByRole("button", { name: "标题一 更多操作" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "删除" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "确认删除?" }))
    await waitFor(() => expect(del).toHaveBeenCalledWith("s1"))
    await waitFor(() => expect(useStore.getState().sessionId).toBeNull())
  })
})
```

Run: `cd frontend && npx vitest run src/components/SessionList.test.tsx` → FAIL。

- [ ] **Step 2: 重写 `SessionList.tsx`**

```tsx
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"
import { RowMenu } from "./RowMenu"

export function SessionList() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const sessionId = useStore((s) => s.sessionId)
  const setSession = useStore((s) => s.setSession)
  const qc = useQueryClient()
  const [renamingId, setRenamingId] = useState<string | null>(null)

  const { data: sessions = [] } = useQuery({
    queryKey: ["sessions", userId],
    queryFn: () => api.listSessions(),
    enabled: !!userId,
  })
  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })

  const current = agents.find((a) => a.id === agentId)
  const mine = agentId ? sessions.filter((s) => s.agent_config_id === agentId) : []
  const label = (s: (typeof mine)[number]) => s.title ?? `会话 ${s.id.slice(0, 6)}`
  const invalidate = () => qc.invalidateQueries({ queryKey: ["sessions", userId] })

  const commitRename = async (id: string, value: string, original: string) => {
    const title = value.trim()
    setRenamingId(null)
    if (!title || title === original) return
    await api.patchSession(id, { title })
    await invalidate()
  }

  const removeSession = async (id: string) => {
    await api.deleteSession(id) // 409 → RowMenu 原位提示
    await invalidate()
    if (useStore.getState().sessionId === id) setSession(null)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="mb-1 truncate px-1 text-xs font-medium tracking-wide text-slate-400">
        {current ? (
          <>
            <span className="text-slate-600">{current.name}</span> 的对话
          </>
        ) : (
          "对话"
        )}
      </div>
      <ul className="min-h-0 flex-1 space-y-0.5 overflow-auto">
        {mine.map((s) => (
          <li
            key={s.id}
            className={`group flex items-center gap-1 rounded-lg pr-1 transition ${
              s.id === sessionId ? "bg-brand-50" : "hover:bg-slate-100"
            }`}
          >
            {renamingId === s.id ? (
              <input
                autoFocus
                defaultValue={label(s)}
                aria-label={`重命名 ${label(s)}`}
                onFocus={(e) => e.target.select()}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void commitRename(s.id, e.currentTarget.value, label(s))
                  else if (e.key === "Escape") setRenamingId(null)
                }}
                onBlur={() => setRenamingId(null)}
                className="mx-1 my-0.5 w-full rounded-lg border border-brand-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
              />
            ) : (
              <>
                <button
                  className={`min-w-0 flex-1 truncate px-2.5 py-2 text-left text-sm ${
                    s.id === sessionId ? "font-medium text-brand-800" : "text-slate-600"
                  }`}
                  onClick={() => setSession(s.id)}
                >
                  {label(s)}
                </button>
                <RowMenu
                  ariaLabel={`${label(s)} 更多操作`}
                  visible={s.id === sessionId}
                  items={[
                    { label: "重命名", onSelect: () => setRenamingId(s.id) },
                    {
                      label: "删除",
                      danger: true,
                      confirmLabel: "确认删除?",
                      onSelect: () => removeSession(s.id),
                    },
                  ]}
                />
              </>
            )}
          </li>
        ))}
        {agentId && mine.length === 0 && (
          <li className="px-2 py-6 text-center text-xs text-slate-400">还没有对话</li>
        )}
        {!agentId && (
          <li className="px-2 py-6 text-center text-xs text-slate-400">先选一个 agent</li>
        )}
      </ul>
    </div>
  )
}
```

- [ ] **Step 3: 测试 + tsc + 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && npx vitest run src/components/SessionList.test.tsx && npx tsc --noEmit
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add frontend/src/components/SessionList.tsx frontend/src/components/SessionList.test.tsx && git commit -m "feat(frontend): session rename + delete via row menu

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Sidebar 自动落位 + AgentSettings 移除创建表单

**Files:** Modify `frontend/src/components/Sidebar.tsx`、`Sidebar.test.tsx`、`settings/AgentSettings.tsx`、`settings/AgentSettings.test.tsx`

- [ ] **Step 1: 扩展测试(失败先行)**

`Sidebar.test.tsx` 追加用例(夹具:`listAgents` mock 返回 `[{id:"a1",…}]`、`listSessions` 返回 `[{id:"s1",agent_config_id:"a1",…}]`,store 初始 `agentId:null, sessionId:null`):

```tsx
it("自动落位:agents 就绪自动选第一个,再选其最近会话", async () => {
  vi.mocked(api.listAgents).mockResolvedValue([
    { id: "a1", user_id: "u1", name: "main", model: "m", provider: "p", thinking_level: null, enabled_tools: [], permissions: {}, key_ref: null },
  ] as never)
  vi.mocked(api.listSessions).mockResolvedValue([
    { id: "s1", user_id: "u1", agent_config_id: "a1", title: null, work_subdir: "workspace", last_context_tokens: null },
  ] as never)
  useStore.setState({ user: { id: "u1", email: "a@e.com" }, userId: "u1", agentId: null, sessionId: null })
  render(wrap(<Sidebar />))
  await waitFor(() => expect(useStore.getState().agentId).toBe("a1"))
  await waitFor(() => expect(useStore.getState().sessionId).toBe("s1"))
})
```

(`vi.mocked(api.listAgents)` 依现有 mock 风格;该文件现用 `vi.mock("../api/client")` 工厂,沿用即可,补 `listSessions` 字段。)

`AgentSettings.test.tsx`:**删除**「创建表单不填模型…」用例(创建职责已移到 AgentList,Task 7 已覆盖),原「shows the create form」改为:

```tsx
it("无选中 agent 时显示空态提示", () => {
  render(wrap(<AgentSettings />))
  expect(screen.getByText("在左侧选择或新建一个 agent")).toBeInTheDocument()
})
```

Run: `cd frontend && npx vitest run src/components/Sidebar.test.tsx src/components/settings/AgentSettings.test.tsx` → 新用例 FAIL。

- [ ] **Step 2: 实现**

`Sidebar.tsx`:imports 加 `useQuery`、`useEffect`;组件体加(`create` mutation 之后):

```tsx
  const sessionId = useStore((s) => s.sessionId)
  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })
  const { data: sessions = [] } = useQuery({
    queryKey: ["sessions", userId],
    queryFn: () => api.listSessions(),
    enabled: !!userId,
  })
  // 自动落位:无选中 agent → 选第一个;选中后无会话 → 选该 agent 最近一条。
  // 新注册用户(注册播种 main+会话)登录即可直接打字;删除当前选中后的兜底也走这里。
  useEffect(() => {
    if (!agentId && agents.length) setAgent(agents[0].id)
  }, [agentId, agents, setAgent])
  useEffect(() => {
    if (!agentId || sessionId) return
    const mine = sessions.filter((s) => s.agent_config_id === agentId)
    if (mine.length) setSession(mine[mine.length - 1].id)
  }, [agentId, sessionId, sessions, setSession])
```

`settings/AgentSettings.tsx`:删除 `draft` state、`createAgent` mutation、`labels` 与整个创建表单分支,`if (!agentId)` 改为:

```tsx
  if (!agentId) {
    return (
      <div className="px-1 py-10 text-center text-sm text-slate-400">
        在左侧选择或新建一个 agent
      </div>
    )
  }
```

同步清理不再使用的 imports(`DEFAULT_MODEL`、`useState` 若仅创建表单在用则按 tsc 报错移除;`setAgent`/`useMutation` 若仅创建在用同理——以 `npx tsc --noEmit` 清零为准)。

- [ ] **Step 3: 测试 + tsc + 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && npx vitest run src/components/Sidebar.test.tsx src/components/settings/ && npx tsc --noEmit
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add frontend/src/components/Sidebar.tsx frontend/src/components/Sidebar.test.tsx frontend/src/components/settings/AgentSettings.tsx frontend/src/components/settings/AgentSettings.test.tsx && git commit -m "feat(frontend): auto-select landing + settings drops creation form

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: 全量回归 + 实跑验证 + 对抗审查 + 收尾

**Files:** 无

- [ ] **Step 1: 前端全量**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: 0 错、全绿。

- [ ] **Step 2: 后端全量**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q && uv run ruff check src tests`
Expected: 全绿(resume flaky 单跑确认)、ruff 干净。

- [ ] **Step 3: 实跑验证(需重启栈 + 登录)**

- 新注册账号 → 落地即有 `main` agent + 会话,直接能发消息。
- 「＋ 新建 Agent」一键直创 → 行变改名输入框(全选 Agent 1)→ Enter 改名生效;Esc 留默认名。
- agent 行 `…`:重命名;删除两次点击(文案「连同全部会话删除?」)→ agent 与其会话消失,落位剩余第一个。
- 会话行 `…`:重命名;删除 → 列表消失;删进行中会话 → 原位「进行中,无法删除」。
- 设置抽屉无选中时显示空态。
截图留证。

- [ ] **Step 4: 对抗式代码审查(Fable 5)**

子 agent(`model: "fable"`)审 `git diff main...HEAD`(只读,diff 自取)。重点:注册播种事务原子性;删除守卫的并发语义(与 try_acquire/heartbeat 的交互、stale running);agent 删除的连带清理是否漏表(skills/memory/docs)与回滚完整性;RowMenu 状态机(确认复位/Esc/点外面/错误超时);改名输入 Enter+blur 双触发;自动落位 effect 与删除落位的循环;跨租户 404。问题 controller 直接修 + 回归。

- [ ] **Step 5: 收尾**

按 superpowers:finishing-a-development-branch:用户常规 = 推 PR,CI 绿后合并。

---

## Self-Review notes

- **Spec 覆盖**:①注册播种(T1,含 409 无残留)✓;②PATCH(T2)✓;③DELETE session 守卫(T3)✓;④DELETE agent 连带+回滚(T4)✓;一键新建/改名态/入口(T7)✓;RowMenu 二次确认+409 提示(T6)✓;会话改名删除(T8)✓;自动落位+设置空态(T9)✓;测试矩阵对应 spec §3 ✓;YAGNI 未越界 ✓。
- **类型一致**:`RowMenuItem{label,danger?,confirmLabel?,onSelect}`(T6 定义,T7/T8 使用);`nextAgentName(string[])`(T5 定义,T7 使用);api `patchSession/deleteSession/deleteAgent`(T5)与各测试 mock 名一致;repo `delete_if_idle/delete_idle_for_agent/count_for_agent`(T3 定义,T3/T4 使用);`default_agent_model`(T1)与测试断言 "DeepSeek-V4-Pro" 一致。
- **无占位符**:全部任务含完整代码;T1 Step4 的存量测试扫尾与 T4 测试的模型必填列核对均给出具体操作方式,非 TODO。
