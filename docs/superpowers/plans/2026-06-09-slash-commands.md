# 斜杠命令面板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Composer 输入框输入 `/` 弹出预设命令面板(Codex 风),命令为纯客户端动作(压缩/状态/新会话/切模型/帮助/跳设置),绝不发给 LLM。

**Architecture:** 前端命令注册表(纯数据 + 纯解析函数)+ `useSlashCommands` hook(把动作接到 store/api/queryClient)+ 两个展示组件(浮层 SlashPalette、通知卡 StatusCard),全部收在 Composer 内,对外 props 不变。后端新增一个受会话锁保护的 `POST /sessions/{id}/compact`,复用已有 `compact()`。

**Tech Stack:** 前端 React19/Vite8/TS/Tailwind + zustand + @tanstack/react-query + vitest/@testing-library;后端 FastAPI + SQLAlchemy + pytest。

参考 spec:`docs/superpowers/specs/2026-06-09-slash-commands-design.md`

---

## 文件结构

**新增**
- `services/backend/tests/test_compact_api.py` — 压缩端点测试
- `frontend/src/components/slash/commands.ts` — 命令注册表 + 解析(纯)
- `frontend/src/components/slash/commands.test.ts` — 纯逻辑单测
- `frontend/src/components/slash/useSlashCommands.ts` — ctx 装配 hook
- `frontend/src/components/slash/SlashPalette.tsx` — 命令/建议浮层(纯展示)
- `frontend/src/components/slash/StatusCard.tsx` — status/help/flash 通知卡(纯展示)

**修改**
- `services/backend/src/agent_cloud_backend/api/sessions.py` — 加 `POST /{id}/compact`
- `frontend/src/api/client.ts` — 加 `compactSession`
- `frontend/src/store.ts` — 导出 `SettingsTab` 类型
- `frontend/src/components/Composer.tsx` — 接面板状态机 + 键盘路由 + 渲染
- `frontend/src/components/Composer.test.tsx` — 套 QueryClientProvider + 斜杠用例

---

## Task 1: 后端 `POST /sessions/{id}/compact` 端点

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/api/sessions.py`
- Test: `services/backend/tests/test_compact_api.py`

后端测试统一在 `services/backend` 下跑:`cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker"`(单文件追加 `tests/test_compact_api.py`)。

- [ ] **Step 1: 写失败测试**

Create `services/backend/tests/test_compact_api.py`:

```python
import uuid

import pytest
from agent_cloud_backend import db as db_module
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker


def _patch_global_sessionmaker(monkeypatch, engine):
    """端点内部 compact()/release 走全局 get_sessionmaker() → 指到测试库。"""
    monkeypatch.setattr(
        db_module, "_sessionmaker", async_sessionmaker(engine, expire_on_commit=False)
    )


async def _seed(engine, user_id: uuid.UUID, n_messages: int) -> uuid.UUID:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        agent = await AgentConfigRepository(db).create(
            AgentConfig(user_id=user_id, name="a", model="m", provider="p")
        )
        await db.flush()
        s = await SessionRepository(db).create_for(user_id, agent.id, None)
        await db.flush()
        for i in range(n_messages):
            await MessageRepository(db).append(
                s.id,
                Message(
                    session_id=s.id,
                    seq=0,  # append 内部按 max+1 重算
                    role="user" if i % 2 == 0 else "assistant",
                    content={"text": f"m{i}", "tool_calls": [], "tool_results": []},
                ),
            )
        await db.commit()
        return s.id


async def _read(engine, session_id: uuid.UUID) -> Session:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        return (
            await db.execute(select(Session).where(Session.id == session_id))
        ).scalar_one()


@pytest.mark.asyncio
async def test_compact_unowned_returns_404(auth_client):
    r = await auth_client.post(f"/sessions/{uuid.uuid4()}/compact")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_compact_busy_returns_409(auth_client, engine, monkeypatch):
    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _seed(engine, uuid.UUID(auth_client.user_id), 0)
    # 占锁:status=running、last_active_at=now(租约未过期)→ try_acquire 失败
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        from sqlalchemy import func
        await db.execute(
            update(Session).where(Session.id == sid).values(status="running", last_active_at=func.now())
        )
        await db.commit()
    r = await auth_client.post(f"/sessions/{sid}/compact")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_compact_progress_true_and_releases(auth_client, engine, monkeypatch):
    _patch_global_sessionmaker(monkeypatch, engine)
    # compact() 会调 worker 摘要 + 提炼记忆 → 打桩,避免真 worker
    async def _fake_summarize(endpoint, req):
        return "SUMMARY"

    async def _noop_extract(session_id, *, settings, reason):
        return None

    monkeypatch.setattr(
        "agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize
    )
    monkeypatch.setattr(
        "agent_cloud_backend.turn.compaction.extract_session_memory", _noop_extract
    )
    sid = await _seed(engine, uuid.UUID(auth_client.user_id), 12)  # > keep_recent(8)

    r = await auth_client.post(f"/sessions/{sid}/compact")
    assert r.status_code == 200
    assert r.json() == {"compacted": True}

    s = await _read(engine, sid)
    assert s.summary_through_seq > -1  # 边界推进了
    assert s.status == "idle"  # 锁已释放


@pytest.mark.asyncio
async def test_compact_nothing_to_compact_returns_false(auth_client, engine, monkeypatch):
    _patch_global_sessionmaker(monkeypatch, engine)

    async def _noop_extract(session_id, *, settings, reason):
        return None

    monkeypatch.setattr(
        "agent_cloud_backend.turn.compaction.extract_session_memory", _noop_extract
    )
    sid = await _seed(engine, uuid.UUID(auth_client.user_id), 2)  # < keep_recent → 无可折叠

    r = await auth_client.post(f"/sessions/{sid}/compact")
    assert r.status_code == 200
    assert r.json() == {"compacted": False}
    assert (await _read(engine, sid)).status == "idle"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_compact_api.py -q`
Expected: FAIL(404 测试外其余因端点不存在返回 405/404 不符;或全 404)。

- [ ] **Step 3: 实现端点**

Edit `services/backend/src/agent_cloud_backend/api/sessions.py` —— 顶部 import 改成:

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.api.ownership import owned_agent, owned_session
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.schemas.session import SessionCreate, SessionRead
from agent_cloud_backend.turn.compaction import compact
```

文件末尾追加 handler:

```python
@router.post("/{session_id}/compact")
async def compact_session(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """手动压缩当前会话上下文。与回合用同一把会话锁:回合进行中 → 409。"""
    await owned_session(session_id, user.id, session)  # 不属本人/不存在 → 404
    acquired = await SessionRepository(session).try_acquire(session_id)
    await session.commit()
    if not acquired:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="session busy")
    try:
        progressed = await compact(
            session_id,
            worker_endpoint=settings.worker_endpoint,
            keep_recent=settings.compaction_keep_recent,
            settings=settings,
        )
    finally:
        async with get_sessionmaker()() as db:  # 独立事务释放锁,绝不被上面影响
            await SessionRepository(db).release(session_id)
            await db.commit()
    return {"compacted": progressed}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_compact_api.py -q`
Expected: 4 passed。

- [ ] **Step 5: lint + 提交**

```bash
cd services/backend && uv run ruff check src/agent_cloud_backend/api/sessions.py tests/test_compact_api.py
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add services/backend/src/agent_cloud_backend/api/sessions.py services/backend/tests/test_compact_api.py
git commit -m "$(cat <<'EOF'
feat(backend): manual compact endpoint POST /sessions/{id}/compact

Lock-guarded (try_acquire→409 if a turn is running), reuses compact() with
the normal keep_recent, releases the lock in a dedicated txn. 404 on
non-owned sessions.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 前端管道(`compactSession` + `SettingsTab` 导出)

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/store.ts`

纯类型/管道改动,无独立测试(Task 3/7 覆盖);完工以 `tsc` 通过为准。

- [ ] **Step 1: 加 `compactSession`**

Edit `frontend/src/api/client.ts` —— 在 `listMessages` 行下方加:

```ts
  compactSession: (id: string) =>
    http<{ compacted: boolean }>(`/sessions/${id}/compact`, { method: "POST" }),
```

- [ ] **Step 2: 导出 `SettingsTab`**

Edit `frontend/src/store.ts`:

顶部(import 之后)加:

```ts
export type SettingsTab = "agent" | "skills" | "keys" | "memory"
```

把接口里两处内联联合改用别名:

```ts
  settingsTab: SettingsTab
```
```ts
  openSettings: (tab?: SettingsTab) => void
```

(实现 `openSettings: (tab = "agent") => ...` 不变。)

- [ ] **Step 3: tsc + 提交**

```bash
cd frontend && npx tsc --noEmit
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/api/client.ts frontend/src/store.ts
git commit -m "$(cat <<'EOF'
feat(frontend): compactSession api + export SettingsTab

Plumbing for the slash-command palette.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 命令注册表 + 解析(纯)

**Files:**
- Create: `frontend/src/components/slash/commands.ts`
- Test: `frontend/src/components/slash/commands.test.ts`

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/slash/commands.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { COMMANDS, dedupeModels, matchCommands, parseInput } from "./commands"

describe("parseInput", () => {
  it("命令模式:斜杠 + 前缀", () => {
    expect(parseInput("/")).toEqual({ mode: "command", prefix: "" })
    expect(parseInput("/co")).toEqual({ mode: "command", prefix: "co" })
  })
  it("匹配不到前缀 → none", () => {
    expect(parseInput("/zzz")).toEqual({ mode: "none" })
  })
  it("路径样输入(斜杠后含斜杠)→ none(直通)", () => {
    expect(parseInput("/usr/bin/python")).toEqual({ mode: "none" })
  })
  it("参数模式:带参命令 + 空格", () => {
    const p = parseInput("/model gpt")
    expect(p.mode).toBe("arg")
    if (p.mode === "arg") {
      expect(p.command.name).toBe("model")
      expect(p.arg).toBe("gpt")
    }
  })
  it("/model 加空格空参 → 参数模式空 arg", () => {
    const p = parseInput("/model ")
    expect(p.mode).toBe("arg")
    if (p.mode === "arg") expect(p.arg).toBe("")
  })
  it("无参命令 + 空格 → none(不进参数模式)", () => {
    expect(parseInput("/status ")).toEqual({ mode: "none" })
  })
  it("普通文本 → none", () => {
    expect(parseInput("hello")).toEqual({ mode: "none" })
  })
})

describe("matchCommands", () => {
  it("空前缀 → 全部", () => {
    expect(matchCommands("")).toHaveLength(COMMANDS.length)
  })
  it("前缀消歧 s*", () => {
    expect(matchCommands("se").map((c) => c.name)).toEqual(["settings"])
    expect(matchCommands("sk").map((c) => c.name)).toEqual(["skills"])
    expect(matchCommands("st").map((c) => c.name)).toEqual(["status"])
  })
})

describe("dedupeModels", () => {
  it("去空 + 去重 + 保序", () => {
    expect(dedupeModels(["a", "a", " b ", "", null, undefined, "c", "b"])).toEqual(["a", "b", "c"])
  })
})

describe("model.suggestions", () => {
  it("按 arg 前缀过滤(trim)", () => {
    const model = COMMANDS.find((c) => c.name === "model")!
    const ctx = { modelSuggestions: () => ["gpt-4o", "gpt-4o-mini", "claude"] } as never
    expect(model.suggestions!(ctx, "gpt")).toEqual(["gpt-4o", "gpt-4o-mini"])
    expect(model.suggestions!(ctx, " cl ")).toEqual(["claude"])
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/slash/commands.test.ts`
Expected: FAIL(模块不存在)。

- [ ] **Step 3: 实现 `commands.ts`**

Create `frontend/src/components/slash/commands.ts`:

```ts
import type { SettingsTab } from "../../store"

export interface StatusInfo {
  agentName: string | null
  model: string | null
  provider: string | null
  sessionTitle: string | null
  sessionIdShort: string | null
  messageCount: number
}

// 命令执行时拿到的上下文:动作接到 store/api/queryClient(在 useSlashCommands 里装配)。
export interface SlashContext {
  newSession: () => Promise<void>
  setModel: (model: string) => Promise<void>
  compact: () => Promise<boolean> // 返回是否真的压缩了
  modelSuggestions: () => string[]
  status: () => StatusInfo
  openSettings: (tab: SettingsTab) => void
  notify: (msg: string) => void // 一行 flash
  showStatus: () => void
  showHelp: () => void
}

export interface SlashCommand {
  name: string // 不含斜杠
  aliases?: string[]
  title: string
  hint: string
  needsArg?: boolean // true → 选中后进参数模式,不立即执行
  run?: (ctx: SlashContext) => void | Promise<void>
  suggestions?: (ctx: SlashContext, arg: string) => string[]
  runWithArg?: (ctx: SlashContext, arg: string) => void | Promise<void>
}

export function dedupeModels(models: (string | null | undefined)[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const m of models) {
    const t = m?.trim()
    if (t && !seen.has(t)) {
      seen.add(t)
      out.push(t)
    }
  }
  return out
}

export const COMMANDS: SlashCommand[] = [
  {
    name: "compact",
    title: "压缩上下文",
    hint: "压缩当前会话",
    run: async (c) => {
      try {
        c.notify((await c.compact()) ? "已压缩当前会话上下文" : "暂无可压缩内容")
      } catch {
        c.notify("压缩失败,请稍后再试")
      }
    },
  },
  { name: "status", title: "状态", hint: "agent / 会话 / 消息数", run: (c) => c.showStatus() },
  {
    name: "new",
    title: "新会话",
    hint: "用当前 agent 开新会话",
    run: async (c) => {
      await c.newSession()
      c.notify("已新建会话")
    },
  },
  {
    name: "model",
    title: "切换模型",
    hint: "改当前 agent 的模型",
    needsArg: true,
    suggestions: (c, arg) => c.modelSuggestions().filter((m) => m.startsWith(arg.trim())),
    runWithArg: async (c, arg) => {
      const m = arg.trim()
      if (!m) return
      try {
        await c.setModel(m)
        c.notify(`已切换模型:${m}`)
      } catch {
        c.notify("切换模型失败")
      }
    },
  },
  { name: "help", title: "帮助", hint: "列出全部命令", run: (c) => c.showHelp() },
  { name: "settings", title: "设置", hint: "打开 Agent 设置", run: (c) => c.openSettings("agent") },
  { name: "memory", title: "记忆", hint: "打开记忆设置", run: (c) => c.openSettings("memory") },
  { name: "skills", title: "技能", hint: "打开技能设置", run: (c) => c.openSettings("skills") },
  { name: "keys", title: "Provider Keys", hint: "打开 Key 设置", run: (c) => c.openSettings("keys") },
]

export type ParsedInput =
  | { mode: "command"; prefix: string }
  | { mode: "arg"; command: SlashCommand; arg: string }
  | { mode: "none" }

export function matchCommands(prefix: string): SlashCommand[] {
  return COMMANDS.filter(
    (c) => c.name.startsWith(prefix) || (c.aliases?.some((a) => a.startsWith(prefix)) ?? false),
  )
}

export function parseInput(text: string): ParsedInput {
  // 参数模式:带参命令 + 空格 + 余下任意(含空)。
  const argMatch = text.match(/^\/(\w+)\s([\s\S]*)$/)
  if (argMatch) {
    const cmd = COMMANDS.find(
      (c) => c.needsArg && (c.name === argMatch[1] || (c.aliases?.includes(argMatch[1]) ?? false)),
    )
    return cmd ? { mode: "arg", command: cmd, arg: argMatch[2] } : { mode: "none" }
  }
  // 命令模式:斜杠 + word 前缀(无空格、无第二个斜杠),且有命令匹配。
  const cmdMatch = text.match(/^\/(\w*)$/)
  if (cmdMatch && matchCommands(cmdMatch[1]).length > 0) {
    return { mode: "command", prefix: cmdMatch[1] }
  }
  return { mode: "none" }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/components/slash/commands.test.ts`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/slash/commands.ts frontend/src/components/slash/commands.test.ts
git commit -m "$(cat <<'EOF'
feat(frontend): slash command registry + input parser

Pure command table + parseInput (command/arg/none three modes) + matchCommands
prefix match + dedupeModels. Unit-tested.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `useSlashCommands` hook

**Files:**
- Create: `frontend/src/components/slash/useSlashCommands.ts`

行为由 Task 7 的 Composer 集成测试覆盖;本任务以 `tsc` 通过为准。

- [ ] **Step 1: 实现 hook**

Create `frontend/src/components/slash/useSlashCommands.ts`:

```ts
import { useQueryClient } from "@tanstack/react-query"
import { api } from "../../api/client"
import { useStore } from "../../store"
import type { AgentConfig, Message, Session } from "../../types"
import { dedupeModels, type SlashContext, type StatusInfo } from "./commands"

// 把命令动作接到 store / api / react-query。读缓存的 key 与各处一致:
// agents/sessions 按 userId 命名,messages 按 sessionId。
export function useSlashCommands(ui: {
  notify: (msg: string) => void
  showStatus: () => void
  showHelp: () => void
}): SlashContext {
  const qc = useQueryClient()
  const userId = useStore((s) => s.userId)
  const sessionId = useStore((s) => s.sessionId)
  const agentId = useStore((s) => s.agentId)
  const setSession = useStore((s) => s.setSession)
  const openSettings = useStore((s) => s.openSettings)

  const agents = (): AgentConfig[] => qc.getQueryData<AgentConfig[]>(["agents", userId]) ?? []

  return {
    newSession: async () => {
      if (!agentId) return
      const s = await api.createSession({ agent_config_id: agentId })
      await qc.invalidateQueries({ queryKey: ["sessions", userId] })
      setSession(s.id)
    },
    setModel: async (model) => {
      if (!agentId) return
      await api.patchAgent(agentId, { model })
      await qc.invalidateQueries({ queryKey: ["agents", userId] })
    },
    compact: async () => {
      if (!sessionId) return false
      const r = await api.compactSession(sessionId)
      return r.compacted
    },
    modelSuggestions: () => dedupeModels(agents().map((a) => a.model)),
    status: (): StatusInfo => {
      const a = agents().find((x) => x.id === agentId) ?? null
      const sessions = qc.getQueryData<Session[]>(["sessions", userId]) ?? []
      const sess = sessions.find((x) => x.id === sessionId) ?? null
      const msgs = sessionId ? (qc.getQueryData<Message[]>(["messages", sessionId]) ?? []) : []
      return {
        agentName: a?.name ?? null,
        model: a?.model ?? null,
        provider: a?.provider ?? null,
        sessionTitle: sess?.title ?? null,
        sessionIdShort: sessionId ? sessionId.slice(0, 8) : null,
        messageCount: msgs.length,
      }
    },
    openSettings,
    notify: ui.notify,
    showStatus: ui.showStatus,
    showHelp: ui.showHelp,
  }
}
```

- [ ] **Step 2: tsc + 提交**

```bash
cd frontend && npx tsc --noEmit
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/slash/useSlashCommands.ts
git commit -m "$(cat <<'EOF'
feat(frontend): useSlashCommands hook wires actions to store/api/cache

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `SlashPalette` 浮层(纯展示)

**Files:**
- Create: `frontend/src/components/slash/SlashPalette.tsx`

- [ ] **Step 1: 实现组件**

Create `frontend/src/components/slash/SlashPalette.tsx`:

```tsx
export interface PaletteItem {
  title: string
  hint?: string
}

// composer 输入框上方的命令/建议浮层。键盘由 Composer 统一路由,这里只展示 + 鼠标选。
// 用 onMouseDown + preventDefault(而非 onClick)以免点选时 textarea 先失焦。
export function SlashPalette({
  items,
  selectedIndex,
  onSelect,
  onHover,
}: {
  items: PaletteItem[]
  selectedIndex: number
  onSelect: (index: number) => void
  onHover: (index: number) => void
}) {
  return (
    <div
      role="listbox"
      className="absolute bottom-full left-0 right-0 z-30 mb-2 max-h-72 overflow-auto rounded-xl border border-slate-200 bg-white p-1.5 shadow-pop"
    >
      {items.map((it, i) => (
        <button
          key={i}
          type="button"
          role="option"
          aria-selected={i === selectedIndex}
          onMouseDown={(e) => {
            e.preventDefault()
            onSelect(i)
          }}
          onMouseEnter={() => onHover(i)}
          className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-1.5 text-left text-sm ${
            i === selectedIndex ? "bg-slate-100" : "hover:bg-slate-50"
          }`}
        >
          <span className="min-w-0 flex-1 truncate text-slate-700">{it.title}</span>
          {it.hint && <span className="shrink-0 text-xs text-slate-400">{it.hint}</span>}
        </button>
      ))}
      <div className="border-t border-slate-100 px-2.5 pb-0.5 pt-1.5 text-[11px] text-slate-400">
        ↑↓ 选择 · Enter 执行 · Esc 关闭
      </div>
    </div>
  )
}
```

- [ ] **Step 2: tsc + 提交**

```bash
cd frontend && npx tsc --noEmit
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/slash/SlashPalette.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): SlashPalette popover (presentational)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `StatusCard` 通知卡(纯展示)

**Files:**
- Create: `frontend/src/components/slash/StatusCard.tsx`

- [ ] **Step 1: 实现组件**

Create `frontend/src/components/slash/StatusCard.tsx`:

```tsx
import { COMMANDS, type StatusInfo } from "./commands"

// composer 上方的「通知槽」:三种内容共用一个浮层位置。
export function StatusCard({
  kind,
  status,
  flash,
  onClose,
}: {
  kind: "status" | "help" | "flash"
  status?: StatusInfo
  flash?: string
  onClose: () => void
}) {
  return (
    <div className="absolute bottom-full left-0 right-0 z-30 mb-2 rounded-xl border border-slate-200 bg-white p-3 shadow-pop">
      <button
        type="button"
        aria-label="关闭"
        onMouseDown={(e) => {
          e.preventDefault()
          onClose()
        }}
        className="absolute right-2 top-2 flex h-6 w-6 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700"
      >
        ✕
      </button>
      {kind === "flash" && <div className="pr-6 text-sm text-slate-700">{flash}</div>}
      {kind === "status" && status && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 pr-6 text-sm">
          <dt className="text-slate-400">Agent</dt>
          <dd className="text-slate-700">{status.agentName ?? "—"}</dd>
          <dt className="text-slate-400">模型</dt>
          <dd className="text-slate-700">{status.model ?? "—"}</dd>
          <dt className="text-slate-400">Provider</dt>
          <dd className="text-slate-700">{status.provider ?? "—"}</dd>
          <dt className="text-slate-400">会话</dt>
          <dd className="text-slate-700">
            {status.sessionTitle ?? "未命名"}{" "}
            <span className="text-slate-400">({status.sessionIdShort ?? "—"})</span>
          </dd>
          <dt className="text-slate-400">消息数</dt>
          <dd className="text-slate-700">{status.messageCount}</dd>
        </dl>
      )}
      {kind === "help" && (
        <div className="pr-6">
          <div className="mb-1.5 text-xs font-medium text-slate-500">斜杠命令</div>
          <ul className="space-y-0.5 text-sm">
            {COMMANDS.map((c) => (
              <li key={c.name} className="flex items-center gap-3">
                <span className="font-mono text-slate-700">/{c.name}</span>
                <span className="text-xs text-slate-400">{c.hint}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: tsc + 提交**

```bash
cd frontend && npx tsc --noEmit
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/slash/StatusCard.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): StatusCard notice slot (status/help/flash)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Composer 集成 + 测试

**Files:**
- Modify: `frontend/src/components/Composer.tsx`
- Test: `frontend/src/components/Composer.test.tsx`(套 provider + 斜杠用例)

- [ ] **Step 1: 写(扩展)失败测试**

Overwrite `frontend/src/components/Composer.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { useStore } from "../store"
import { Composer } from "./Composer"

const USER = "u1"

function setup(opts?: { disabled?: boolean }) {
  const qc = new QueryClient()
  useStore.setState({ userId: USER, agentId: "a1", sessionId: "s1" })
  qc.setQueryData(
    ["agents", USER],
    [
      { id: "a1", name: "Coder", model: "gpt-4o", provider: "openai", thinking_level: null, enabled_tools: [], permissions: {}, key_ref: null },
      { id: "a2", name: "Other", model: "claude-x", provider: "anthropic", thinking_level: null, enabled_tools: [], permissions: {}, key_ref: null },
    ],
  )
  qc.setQueryData(["sessions", USER], [{ id: "s1", user_id: USER, agent_config_id: "a1", title: "T", work_subdir: "workspace" }])
  qc.setQueryData(["messages", "s1"], [{ id: "m1" }, { id: "m2" }, { id: "m3" }])
  const onSend = vi.fn()
  render(
    <QueryClientProvider client={qc}>
      <Composer disabled={opts?.disabled ?? false} onSend={onSend} onStop={() => {}} />
    </QueryClientProvider>,
  )
  return { onSend }
}

const box = () => screen.getByRole("textbox")
const type = (v: string) => fireEvent.change(box(), { target: { value: v } })

afterEach(() => {
  useStore.setState({ userId: null, agentId: null, sessionId: null, settingsOpen: false })
  vi.restoreAllMocks()
})

describe("Composer 基础", () => {
  it("idle 显示发送并回调 onSend", () => {
    const { onSend } = setup()
    type("hi")
    fireEvent.click(screen.getByText("发送"))
    expect(onSend).toHaveBeenCalledWith("hi")
  })
  it("streaming 显示停止", () => {
    setup({ disabled: true })
    expect(screen.queryByText("发送")).not.toBeInTheDocument()
    expect(screen.getByText("停止")).toBeInTheDocument()
  })
})

describe("斜杠面板", () => {
  it("输入 / 列出全部命令;/co 只剩 compact", () => {
    setup()
    type("/")
    expect(screen.getByText("压缩上下文")).toBeInTheDocument()
    expect(screen.getByText("切换模型")).toBeInTheDocument()
    type("/co")
    expect(screen.getByText("压缩上下文")).toBeInTheDocument()
    expect(screen.queryByText("切换模型")).not.toBeInTheDocument()
  })

  it("↑↓ 改变高亮", () => {
    setup()
    type("/")
    const opts = screen.getAllByRole("option")
    expect(opts[0]).toHaveAttribute("aria-selected", "true")
    fireEvent.keyDown(box(), { key: "ArrowDown" })
    expect(screen.getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true")
  })

  it("/compact Enter → 调 compactSession 并 flash", async () => {
    const spy = vi.spyOn(api, "compactSession").mockResolvedValue({ compacted: true })
    setup()
    type("/compact")
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(spy).toHaveBeenCalledWith("s1")
    expect(await screen.findByText("已压缩当前会话上下文")).toBeInTheDocument()
  })

  it("/model → 参数模式列建议 → 选中调 patchAgent", async () => {
    const spy = vi.spyOn(api, "patchAgent").mockResolvedValue({} as never)
    setup()
    type("/model")
    fireEvent.keyDown(box(), { key: "Enter" }) // 进参数模式,text → "/model "
    expect(box()).toHaveValue("/model ")
    const opt = await screen.findByText("gpt-4o")
    fireEvent.mouseDown(opt)
    expect(spy).toHaveBeenCalledWith("a1", { model: "gpt-4o" })
  })

  it("/new Enter → 调 createSession", () => {
    const spy = vi.spyOn(api, "createSession").mockResolvedValue({ id: "s2" } as never)
    setup()
    type("/new")
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(spy).toHaveBeenCalledWith({ agent_config_id: "a1" })
  })

  it("/memory Enter → 打开记忆设置", () => {
    setup()
    type("/memory")
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(useStore.getState().settingsOpen).toBe(true)
    expect(useStore.getState().settingsTab).toBe("memory")
  })

  it("/status Enter → 状态卡显示 agent/模型", async () => {
    setup()
    type("/status")
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(await screen.findByText("Coder")).toBeInTheDocument()
    expect(screen.getByText("gpt-4o")).toBeInTheDocument()
  })

  it("无匹配 / 路径样输入 → 直通发送", () => {
    const { onSend } = setup()
    type("/usr/bin/python")
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(onSend).toHaveBeenCalledWith("/usr/bin/python")
  })

  it("Esc 关面板后 Enter → 直通发送", () => {
    const { onSend } = setup()
    type("/status")
    expect(screen.getByRole("listbox")).toBeInTheDocument()
    fireEvent.keyDown(box(), { key: "Escape" })
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(onSend).toHaveBeenCalledWith("/status")
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/Composer.test.tsx`
Expected: FAIL(Composer 尚未接面板;且未套 provider 时旧实现会因新 hook 报错)。

- [ ] **Step 3: 实现 Composer 集成**

Overwrite `frontend/src/components/Composer.tsx`:

```tsx
import { useEffect, useRef, useState } from "react"
import { matchCommands, parseInput } from "./slash/commands"
import { SlashPalette } from "./slash/SlashPalette"
import { StatusCard } from "./slash/StatusCard"
import { useSlashCommands } from "./slash/useSlashCommands"
import { Button, Textarea } from "./ui"

type Notice = { kind: "flash"; flash: string } | { kind: "status" } | { kind: "help" } | null
interface Entry {
  title: string
  hint?: string
  exec: () => void
}

export function Composer({
  disabled,
  onSend,
  onStop,
}: {
  disabled: boolean
  onSend: (text: string) => void
  onStop?: () => void
}) {
  const [text, setText] = useState("")
  const [sel, setSel] = useState(0)
  const [dismissed, setDismissed] = useState(false) // Esc 关面板,保留文本走直通
  const [notice, setNotice] = useState<Notice>(null)
  const wrapRef = useRef<HTMLDivElement>(null)

  const ctx = useSlashCommands({
    notify: (msg) => setNotice({ kind: "flash", flash: msg }),
    showStatus: () => setNotice({ kind: "status" }),
    showHelp: () => setNotice({ kind: "help" }),
  })

  // 由文本派生面板条目(命令模式 / 参数模式)。
  const parsed = parseInput(text)
  const entries: Entry[] = []
  if (!dismissed && !disabled) {
    if (parsed.mode === "command") {
      for (const cmd of matchCommands(parsed.prefix)) {
        entries.push({
          title: cmd.title,
          hint: "/" + cmd.name,
          exec: () => {
            if (cmd.needsArg) {
              setText(`/${cmd.name} `)
              setSel(0)
            } else {
              void cmd.run?.(ctx)
              setText("")
            }
          },
        })
      }
    } else if (parsed.mode === "arg") {
      const { command, arg } = parsed
      const sugg = command.suggestions?.(ctx, arg) ?? []
      for (const s of sugg) {
        entries.push({
          title: s,
          hint: "模型",
          exec: () => {
            void command.runWithArg?.(ctx, s)
            setText("")
          },
        })
      }
      const trimmed = arg.trim()
      if (trimmed && !sugg.includes(trimmed)) {
        entries.push({
          title: `应用 "${trimmed}"`,
          hint: "自由输入",
          exec: () => {
            void command.runWithArg?.(ctx, trimmed)
            setText("")
          },
        })
      }
    }
  }
  const paletteOpen = entries.length > 0
  const safeSel = paletteOpen ? Math.min(sel, entries.length - 1) : 0

  // flash 自动消失;status/help 常驻直到手动关。
  useEffect(() => {
    if (notice?.kind !== "flash") return
    const t = setTimeout(() => setNotice(null), 4000)
    return () => clearTimeout(t)
  }, [notice])

  // 点 composer 外面 → 关通知卡(面板随文本变化自然收起)。
  useEffect(() => {
    if (!notice) return
    const onDoc = (e: Event) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setNotice(null)
    }
    document.addEventListener("pointerdown", onDoc)
    return () => document.removeEventListener("pointerdown", onDoc)
  }, [notice])

  const send = () => {
    const t = text.trim()
    if (!t || disabled) return
    onSend(t)
    setText("")
  }

  return (
    <div className="border-t border-slate-200 bg-white/80 p-3 backdrop-blur">
      <div ref={wrapRef} className="relative mx-auto flex max-w-5xl items-end gap-2">
        {notice && (
          <StatusCard
            kind={notice.kind}
            status={notice.kind === "status" ? ctx.status() : undefined}
            flash={notice.kind === "flash" ? notice.flash : undefined}
            onClose={() => setNotice(null)}
          />
        )}
        {paletteOpen && (
          <SlashPalette
            items={entries.map((e) => ({ title: e.title, hint: e.hint }))}
            selectedIndex={safeSel}
            onSelect={(i) => entries[i]?.exec()}
            onHover={(i) => setSel(i)}
          />
        )}
        <Textarea
          className="min-h-[44px] flex-1"
          placeholder={disabled ? "生成中…" : "说点什么(/ 唤起命令,Enter 发送,Shift+Enter 换行)"}
          rows={1}
          value={text}
          disabled={disabled}
          onChange={(e) => {
            setText(e.target.value)
            setSel(0)
            setDismissed(false)
          }}
          onKeyDown={(e) => {
            if (paletteOpen) {
              if (e.key === "ArrowDown") {
                e.preventDefault()
                setSel((i) => Math.min(i + 1, entries.length - 1))
              } else if (e.key === "ArrowUp") {
                e.preventDefault()
                setSel((i) => Math.max(i - 1, 0))
              } else if (e.key === "Enter" || e.key === "Tab") {
                e.preventDefault()
                entries[safeSel]?.exec()
              } else if (e.key === "Escape") {
                e.preventDefault()
                setDismissed(true)
              }
              return
            }
            if (e.key === "Escape" && notice) {
              e.preventDefault()
              setNotice(null)
            } else if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
        />
        {disabled && onStop ? (
          <Button variant="secondary" className="h-11" onClick={onStop}>
            停止
          </Button>
        ) : (
          <Button className="h-11" disabled={disabled} onClick={send}>
            发送
          </Button>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/components/Composer.test.tsx`
Expected: 全 PASS。

- [ ] **Step 5: 提交**

```bash
cd frontend && npx tsc --noEmit
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/Composer.tsx frontend/src/components/Composer.test.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): slash-command palette in composer

Type "/" to open the command palette: compact, status, new session, switch
model, help, and settings-nav. Keyboard-driven, client-side actions only.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: 全量回归 + 实跑验证

**Files:** 无(验证 + 收尾)

- [ ] **Step 1: 前端全量**

Run: `cd frontend && npx tsc --noEmit && npx vitest run && npx biome check src 2>/dev/null || npx eslint src 2>/dev/null || true`
Expected: tsc 0 错、vitest 全绿。(lint 命令以项目实际为准。)

- [ ] **Step 2: 后端全量**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q && uv run ruff check src tests`
Expected: 全绿、ruff 干净。

- [ ] **Step 3: 实跑验证(preview)**

起前端预览,逐条验证(参照 [feedback_preview_react_inputs]:React 输入用原生 value setter + input 事件,`preview_fill` 不触发 onChange):
- 输入 `/` → 浮层列全部命令;`/co` → 只剩压缩。
- ↑↓ 高亮移动;Enter 执行。
- `/status` → 状态卡显示当前 agent/模型/会话/消息数。
- `/model ` → 列出已有模型;选一个 → 设置里该 agent 模型已变(切到设置页确认)。
- `/memory`、`/skills`、`/keys`、`/settings` → 抽屉打开到对应 tab。
- `/new` → 切到空会话,侧栏多一条会话。
- `/compact` → flash 反馈(消息够多→「已压缩」,否则「暂无可压缩」)。
- 普通消息 `/usr/...` 与 Esc 后回车 → 正常发送。

截图留证。

- [ ] **Step 4: 对抗式代码审查**

按 [feedback_dev_workflow]:实现完成后做对抗审查。用 Opus 子 agent(`model: "opus"`)审本分支 diff(diff 内联给它,勿让它大批量写文件);重点:面板状态机竞态(快速连按/IME 回车/dismissed 重置)、压缩端点锁的 TOCTOU 与释放、跨租户 404、key 不外泄。发现问题 controller 直接改 + 回归。

- [ ] **Step 5: 收尾**

按 superpowers:finishing-a-development-branch 给选项(合并 / PR / 保留 / 丢弃)。

---

## Self-Review notes

- **Spec 覆盖**:交互三态(parse)✓、核心 5 命令 ✓、nav 4 命令 ✓、`/model` 建议+自由输入 ✓、`/compact` 端点+锁 ✓、`/new` 非破坏 ✓、测试(后端 owned/409/进展/无可压缩 + 前端解析/键盘/派发/直通)✓。
- **类型一致**:`SlashContext.compact: () => Promise<boolean>`(hook、command、Composer 三处一致);`SettingsTab` 由 store 导出,commands/useSlashCommands 共用;query key `["agents",userId]`/`["sessions",userId]`/`["messages",sessionId]` 与 SessionList/AgentList/ChatView 一致。
- **无占位符**:每步含完整代码/命令/预期。
