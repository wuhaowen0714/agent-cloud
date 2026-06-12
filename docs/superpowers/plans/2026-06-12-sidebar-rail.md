# 侧栏 Agent rail 重设计 Implementation Plan

> **For agentic workers:** 按用户既定工作流,controller 直接 TDD 实现(子 agent 仅做对抗审查);本 plan 任务全部在 worktree `worktree-feat-sidebar-rail` 内执行。Steps 用 checkbox 跟踪。

**Goal:** 侧栏重组为「左 46px agent 头像 rail + 右会话面板」,会话按 last_active_at 降序时间分组,agent 配置入口收进面板头部,解决主从倒置/双+按钮/三职行/双高亮/动作结果分离五个问题。

**Architecture:** 纯前端重组,后端零改动。`Sidebar` 变组合器(rail | 面板),新建 `AgentRail`(替代 `AgentList`)与 `AgentHeader`;`SessionList` 去区头加分组;`AccountMenu` 收圆头像进 rail 底部。浮层(tooltip/账户菜单)遵循仓内既有约束:**aside 的 backdrop-blur 使 fixed 后代相对侧栏解析 → 一律 portal 到 body**(RowMenu 已验证的模式)。

**Tech Stack:** React19 + zustand + react-query + Tailwind 3.4 + vitest/RTL(jsdom)。

参考文件:`Sidebar.tsx`(自动落位效应)、`AgentList.tsx`(create/rename/delete 逻辑,将迁移)、`SessionList.tsx`、`RowMenu.tsx`(portal 浮层模式)、`AccountMenu.tsx`、`time.ts`/`time.test.ts`(now 注入测试模式)。

---

## File Structure

- Modify `frontend/src/types.ts` — `Session` 补 `last_active_at: string`(后端 SessionRead 已返回)。
- Modify `frontend/src/time.ts` + `time.test.ts` — 新增 `timeGroupLabel`。
- Create `frontend/src/components/AgentRail.tsx` + `AgentRail.test.tsx` — rail(logo/头像/新建/账户)+ 导出 `agentInitial`/`agentColor` 纯函数。
- Modify `frontend/src/components/AccountMenu.tsx` + 测试 — 圆头像触发器 + 右上 portal 菜单 + 菜单内邮箱行。
- Create `frontend/src/components/AgentHeader.tsx` + 测试 — 名字/模型/⚙/…菜单/改名态(逻辑自 AgentList 迁移)。
- Modify `frontend/src/components/SessionList.tsx` + 测试 — 去区头、last_active_at 降序、时间分组、空态。
- Modify `frontend/src/components/Sidebar.tsx` + 测试 — 重组为 rail|面板,新对话主按钮,自动落位改"最近活跃"。
- Delete `frontend/src/components/AgentList.tsx` + `AgentList.test.tsx`(用例迁入 AgentRail/AgentHeader)。

所有命令在 `frontend/` 目录下执行;提交信息一律带 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

---

## Task SR-1: timeGroupLabel + Session 类型补字段

**Files:** Modify `src/time.ts`、`src/time.test.ts`、`src/types.ts`

- [ ] **Step 1: 失败测试**(time.test.ts 追加;沿用文件既有「无后缀 ISO 按本地解析 + 注入 now」模式)

```ts
import { fmtTime, timeGroupLabel } from "./time"

describe("timeGroupLabel", () => {
  const now = new Date("2026-06-12T20:00:00")
  it("今天/昨天按本地日历日", () => {
    expect(timeGroupLabel("2026-06-12T00:01:00", now)).toBe("今天")
    expect(timeGroupLabel("2026-06-11T23:59:00", now)).toBe("昨天")
  })
  it("前 7 天 = 2~7 日前;前 30 天 = 8~30;更早", () => {
    expect(timeGroupLabel("2026-06-10T12:00:00", now)).toBe("前 7 天")
    expect(timeGroupLabel("2026-06-05T12:00:00", now)).toBe("前 7 天")
    expect(timeGroupLabel("2026-06-04T12:00:00", now)).toBe("前 30 天")
    expect(timeGroupLabel("2026-05-13T12:00:00", now)).toBe("前 30 天")
    expect(timeGroupLabel("2026-05-12T12:00:00", now)).toBe("更早")
    expect(timeGroupLabel("2025-01-01T12:00:00", now)).toBe("更早")
  })
  it("未来时间(时钟偏差)归今天;坏值归更早", () => {
    expect(timeGroupLabel("2026-06-13T08:00:00", now)).toBe("今天")
    expect(timeGroupLabel("not-a-date", now)).toBe("更早")
  })
  it("Z 后缀按本地时区分日(TZ 钉 Asia/Shanghai):UTC 昨日 17:00 = 本地今日 01:00", () => {
    expect(timeGroupLabel("2026-06-11T17:00:00Z", now)).toBe("今天")
  })
})
```

(顶部 import 行替换原 `import { fmtTime } from "./time"`。)

- [ ] **Step 2: 跑红** — `npx vitest run src/time.test.ts`,预期 FAIL(timeGroupLabel 未导出)。

- [ ] **Step 3: 实现**(time.ts 追加)

```ts
// 会话列表时间分组:按本地日历日距今天数分档。未来(时钟偏差)归今天;坏值归更早。
export function timeGroupLabel(iso: string, now: Date = new Date()): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "更早"
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const days = Math.round((startOf(now) - startOf(d)) / 86_400_000)
  if (days <= 0) return "今天"
  if (days === 1) return "昨天"
  if (days <= 7) return "前 7 天"
  if (days <= 30) return "前 30 天"
  return "更早"
}
```

types.ts 的 `Session` 行改为:

```ts
export interface Session { id: string; user_id: string; agent_config_id: string; title: string | null; work_subdir: string; last_active_at: string; last_context_tokens: number | null }
```

- [ ] **Step 4: 跑绿 + lint** — `npx vitest run src/time.test.ts && npm run lint`(既有 fixture 都经 `as never` 注入,类型不破;运行期缺字段的 fixture 在后续任务补)。

- [ ] **Step 5: 提交** — `git add -A && git commit -m "feat(frontend): timeGroupLabel + Session.last_active_at type"`

---

## Task SR-2: AgentRail(头像/配色/portal tooltip/新建/账户槽)

**Files:** Create `src/components/AgentRail.tsx`、`src/components/AgentRail.test.tsx`

- [ ] **Step 1: 失败测试**(AgentRail.test.tsx,fixture 仿 AgentList.test)

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { useStore } from "../store"
import { AgentRail, agentColor, agentInitial } from "./AgentRail"

const A1 = { id: "a1", user_id: "u1", name: "main", model: "DeepSeek-V4-Pro", provider: "openai",
  thinking_level: null, enabled_tools: [], permissions: {}, key_ref: null }
let agents: (typeof A1)[]
const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>
)
beforeEach(() => {
  agents = [A1, { ...A1, id: "a2", name: "Agent 2" }]
  useStore.setState({ user: { id: "u1", email: "alice@e.com" }, userId: "u1", agentId: "a1", sessionId: null })
  vi.spyOn(api, "listAgents").mockImplementation(() => Promise.resolve([...agents] as never))
})
afterEach(() => {
  useStore.setState({ user: null, userId: null, agentId: null, sessionId: null })
  vi.restoreAllMocks()
})

describe("agentInitial / agentColor", () => {
  it("字母+数字名取两位,其余取首字符大写", () => {
    expect(agentInitial("Agent 1")).toBe("A1")
    expect(agentInitial("agent12")).toBe("A12")
    expect(agentInitial("hello")).toBe("H")
    expect(agentInitial("主力")).toBe("主")
    expect(agentInitial("  ")).toBe("?")
  })
  it("配色稳定且来自色板", () => {
    expect(agentColor("main")).toBe(agentColor("main"))
    expect(agentColor("main")).toMatch(/^bg-(teal|violet|sky|amber|rose|emerald)-100 text-\1-700$/)
  })
})

describe("AgentRail", () => {
  it("渲染头像缩写;点未选中头像切换;点已选中不重置", async () => {
    render(wrap(<AgentRail onCreated={() => {}} />))
    expect(await screen.findByRole("button", { name: "Agent 2" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Agent 2" }))
    expect(useStore.getState().agentId).toBe("a2")
    useStore.setState({ agentId: "a1", sessionId: "keep" })
    fireEvent.click(screen.getByRole("button", { name: "main" }))
    expect(useStore.getState().sessionId).toBe("keep") // setAgent 未被调用(会清 sessionId)
  })
  it("hover 头像弹「名字 · 模型」tooltip(portal 到 body)", async () => {
    render(wrap(<AgentRail onCreated={() => {}} />))
    fireEvent.mouseEnter(await screen.findByRole("button", { name: "main" }))
    expect(await screen.findByText("main · DeepSeek-V4-Pro")).toBeInTheDocument()
    fireEvent.mouseLeave(screen.getByRole("button", { name: "main" }))
    expect(screen.queryByText("main · DeepSeek-V4-Pro")).not.toBeInTheDocument()
  })
  it("+ 新建:默认名直创,成功选中并回调 onCreated", async () => {
    const created = { ...A1, id: "a9", name: "Agent 3" }
    vi.spyOn(api, "createAgent").mockImplementation(() => {
      agents = [...agents, created]
      return Promise.resolve(created as never)
    })
    const onCreated = vi.fn()
    render(wrap(<AgentRail onCreated={onCreated} />))
    fireEvent.click(await screen.findByRole("button", { name: "新建 Agent" }))
    await waitFor(() =>
      expect(api.createAgent).toHaveBeenCalledWith({ name: "Agent 3", model: "DeepSeek-V4-Pro", provider: "openai" }),
    )
    await waitFor(() => expect(useStore.getState().agentId).toBe("a9"))
    expect(onCreated).toHaveBeenCalledWith("a9")
  })
})
```

(注:`agentInitial("agent12")` 走字母+数字分支 → `A12`;`nextAgentName(["main","Agent 2"])` 产 `Agent 3`,createAgent 断言据此。)

- [ ] **Step 2: 跑红** — `npx vitest run src/components/AgentRail.test.tsx`,预期 FAIL(模块不存在)。

- [ ] **Step 3: 实现 AgentRail.tsx**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useState } from "react"
import { createPortal } from "react-dom"
import { nextAgentName } from "../agentConfig"
import { api } from "../api/client"
import { DEFAULT_MODEL } from "../models"
import { useStore } from "../store"
import { AccountMenu } from "./AccountMenu"

export function agentInitial(name: string): string {
  const t = name.trim()
  const m = t.match(/^([A-Za-z])[A-Za-z]*\s*(\d+)$/)
  if (m) return `${m[1].toUpperCase()}${m[2]}`
  const c = t.charAt(0)
  return c ? c.toUpperCase() : "?"
}

const PALETTE = [
  "bg-teal-100 text-teal-700", "bg-violet-100 text-violet-700", "bg-sky-100 text-sky-700",
  "bg-amber-100 text-amber-700", "bg-rose-100 text-rose-700", "bg-emerald-100 text-emerald-700",
]
export function agentColor(name: string): string {
  let h = 0
  for (const ch of name) h = (h + (ch.codePointAt(0) ?? 0)) % 9973
  return PALETTE[h % PALETTE.length]
}

// rail tooltip:portal 到 body + fixed(aside 的 backdrop-blur 会把 fixed 后代的包含块
// 变成侧栏 → 不能留在 aside 内;且头像列 overflow-y-auto 会裁剪 absolute 浮层)。
function RailTip({ text, anchor }: { text: string; anchor: DOMRect }) {
  return createPortal(
    <div
      style={{ top: anchor.top + anchor.height / 2, left: anchor.right + 8 }}
      className="pointer-events-none fixed z-30 -translate-y-1/2 whitespace-nowrap rounded-md bg-slate-800 px-1.5 py-0.5 text-[11px] text-white"
    >
      {text}
    </div>,
    document.body,
  )
}

/** 左侧 46px rail:品牌方块 / agent 头像列(点选切换)/ 新建 / 账户。只管「切谁」,无管理操作。 */
export function AgentRail({ onCreated }: { onCreated: (id: string) => void }) {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const setAgent = useStore((s) => s.setAgent)
  const qc = useQueryClient()
  const [tip, setTip] = useState<{ text: string; anchor: DOMRect } | null>(null)

  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })

  const create = useMutation({
    mutationFn: () =>
      api.createAgent({ name: nextAgentName(agents.map((a) => a.name)), model: DEFAULT_MODEL, provider: "openai" }),
    onSuccess: async (a) => {
      await qc.invalidateQueries({ queryKey: ["agents", userId] })
      setAgent(a.id)
      onCreated(a.id) // 面板头部进入改名态
    },
  })

  const showTip = (text: string) => (e: React.MouseEvent<HTMLElement>) =>
    setTip({ text, anchor: e.currentTarget.getBoundingClientRect() })

  return (
    <div className="flex w-[46px] flex-none flex-col items-center gap-2 border-r border-slate-200/70 bg-slate-50 py-3">
      <span
        onMouseEnter={showTip("Agent Cloud")}
        onMouseLeave={() => setTip(null)}
        className="flex h-[30px] w-[30px] items-center justify-center rounded-[9px] bg-gradient-to-br from-brand-400 to-brand-600 text-[13px] font-bold text-white shadow-sm"
      >
        A
      </span>
      <span className="w-[22px] border-t border-slate-200" />
      <div className="flex min-h-0 flex-1 flex-col items-center gap-2 overflow-y-auto">
        {agents.map((a) => {
          const active = a.id === agentId
          return (
            <button
              key={a.id}
              type="button"
              aria-label={a.name}
              aria-current={active || undefined}
              onMouseEnter={showTip(`${a.name} · ${a.model}`)}
              onMouseLeave={() => setTip(null)}
              onClick={() => {
                if (a.id !== agentId) setAgent(a.id) // 点已选中不重置(setAgent 会清会话选择)
              }}
              className={`flex h-[30px] w-[30px] flex-none items-center justify-center rounded-full text-[11px] font-semibold transition ${agentColor(a.name)} ${
                active ? "ring-2 ring-brand-500 ring-offset-1" : "hover:ring-2 hover:ring-slate-300 hover:ring-offset-1"
              }`}
            >
              {agentInitial(a.name)}
            </button>
          )
        })}
      </div>
      <button
        type="button"
        aria-label="新建 Agent"
        disabled={create.isPending}
        onMouseEnter={showTip("新建 Agent")}
        onMouseLeave={() => setTip(null)}
        onClick={() => create.mutate()}
        className="flex h-[30px] w-[30px] flex-none items-center justify-center rounded-full border border-dashed border-slate-300 text-slate-400 transition hover:border-slate-400 hover:text-slate-600 disabled:opacity-50"
      >
        <Plus size={14} />
      </button>
      <AccountMenu />
      {tip && <RailTip text={tip.text} anchor={tip.anchor} />}
    </div>
  )
}
```

- [ ] **Step 4: 跑绿** — `npx vitest run src/components/AgentRail.test.tsx`(AccountMenu 此时仍是旧版整行样式,渲染在 46px rail 里只是难看,不影响测试;SR-3 立刻收拢)。

- [ ] **Step 5: 提交** — `git add -A && git commit -m "feat(frontend): AgentRail — avatar rail with portal tooltips and create flow"`

---

## Task SR-3: AccountMenu 收圆头像 + 右上 portal 菜单

**Files:** Modify `src/components/AccountMenu.tsx`、`src/components/AccountMenu.test.tsx`

- [ ] **Step 1: 改测试为新契约**(整文件替换 describe 内容)

```tsx
describe("AccountMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useStore.setState({ user: { id: "u1", email: "alice@example.com" }, userId: "u1" })
  })

  it("触发器是圆头像(不直接显示邮箱);菜单内含邮箱行 / Provider Keys / 登出", () => {
    render(<AccountMenu />)
    expect(screen.queryByText("alice@example.com")).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "账户" }))
    expect(screen.getByText("alice@example.com")).toBeInTheDocument()
    expect(screen.getByText("登出")).toBeInTheDocument()
    expect(screen.getByText("Provider Keys")).toBeInTheDocument()
    expect(screen.queryByText("工作区文件")).not.toBeInTheDocument()
  })

  it("logs out: calls api.logout then clears the store user", async () => {
    render(<AccountMenu />)
    fireEvent.click(screen.getByRole("button", { name: "账户" }))
    fireEvent.click(screen.getByText("登出"))
    await waitFor(() => expect(api.logout).toHaveBeenCalled())
    await waitFor(() => expect(useStore.getState().user).toBeNull())
  })
})
```

- [ ] **Step 2: 跑红** — `npx vitest run src/components/AccountMenu.test.tsx`,预期 FAIL(无「账户」按钮)。

- [ ] **Step 3: 实现** — AccountMenu.tsx 的 return 块替换(状态/外点关闭/doLogout 逻辑保留;外点监听需同时查 portal 菜单 ref,仿 RowMenu):

```tsx
  const menuRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ left: 0, bottom: 0 })
  // useEffect 外点关闭改为:if (ref.current?.contains(t) || menuRef.current?.contains(t)) return; setOpen(false)

  if (!user) return null
  const initial = user.email.charAt(0).toUpperCase()
  const item = "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm text-slate-600 hover:bg-slate-100"
  const openMenu = () => {
    const r = ref.current?.getBoundingClientRect()
    if (r) setPos({ left: r.right + 8, bottom: window.innerHeight - r.bottom })
    setOpen(true)
  }
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label="账户"
        onClick={() => (open ? setOpen(false) : openMenu())}
        className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-brand-600 text-xs font-semibold text-white shadow-sm transition hover:ring-2 hover:ring-slate-300 hover:ring-offset-1"
      >
        {initial}
      </button>
      {open &&
        createPortal(
          <div
            ref={menuRef}
            style={{ left: pos.left, bottom: pos.bottom }}
            className="fixed z-30 w-52 rounded-xl border border-slate-200 bg-white p-1.5 shadow-pop"
          >
            <div className="truncate px-2.5 py-1.5 text-xs text-slate-400">{user.email}</div>
            <div className="mx-1 my-1 border-t border-slate-100" />
            <button className={item} onClick={() => { openSettings("keys"); setOpen(false) }}>
              <KeyRound size={15} className="shrink-0 text-slate-400" />
              <span>Provider Keys</span>
            </button>
            <button className={`${item} hover:text-red-600`} onClick={doLogout}>
              <LogOut size={15} className="shrink-0" />
              <span>登出</span>
            </button>
          </div>,
          document.body,
        )}
    </div>
  )
```

(import 增 `createPortal`;`ChevronDown` import 删除。portal + fixed 同 RowMenu 理由:aside backdrop-blur 是 fixed 包含块,留在 aside 内反而错位;用 left+bottom 锚定使菜单底边贴触发器底边、向右上方展开。)

- [ ] **Step 4: 跑绿 + 受影响处** — `npx vitest run src/components/AccountMenu.test.tsx src/components/Sidebar.test.tsx`;Sidebar 测试此时会红(邮箱不再直显)——属预期,SR-6 一并改,此步只确认 AccountMenu 自身绿。

- [ ] **Step 5: 提交** — `git add src/components/AccountMenu.tsx src/components/AccountMenu.test.tsx && git commit -m "feat(frontend): compact avatar AccountMenu with portal flyout"`

---

## Task SR-4: SessionList 分组排序去区头

**Files:** Modify `src/components/SessionList.tsx`、`src/components/SessionList.test.tsx`

- [ ] **Step 1: 改/加测试** — fixture 补 `last_active_at`;新增分组用例;区头断言删除:

```tsx
const S1 = { id: "s1", user_id: "u1", agent_config_id: "a1", title: "标题一", work_subdir: "workspace",
  last_active_at: new Date().toISOString(), last_context_tokens: null }

it("按 last_active_at 降序 + 时间分组标签", async () => {
  const hours = (n: number) => new Date(Date.now() - n * 3600_000).toISOString()
  vi.spyOn(api, "listSessions").mockResolvedValue([
    { ...S1, id: "old", title: "旧会话", last_active_at: hours(24 * 40) },
    { ...S1, id: "yesterday", title: "昨日会话", last_active_at: hours(26) },
    { ...S1, id: "now", title: "刚刚会话", last_active_at: hours(0) },
  ] as never)
  render(wrap(<SessionList />))
  await screen.findByText("刚刚会话")
  const labels = screen.getAllByRole("listitem").map((li) => li.textContent)
  const idx = (t: string) => labels.findIndex((x) => x?.includes(t))
  expect(idx("今天")).toBeLessThan(idx("刚刚会话"))
  expect(idx("刚刚会话")).toBeLessThan(idx("昨日会话"))
  expect(idx("昨日会话")).toBeLessThan(idx("旧会话"))
  expect(screen.getByText("今天")).toBeInTheDocument()
  expect(screen.getByText("更早")).toBeInTheDocument()
  expect(screen.queryByText(/的对话/)).not.toBeInTheDocument() // 区头已删
})
```

(注:`hours(26)` 在 20:00 后会落「今天」之前的「昨天」或当 02:00 跑测试落「前 7 天」——为确定性,「昨日会话」改用 `hours(36)`?不行,36h 在上午仍可能跨两日。**确定做法**:夹具直接用本地日历日构造:`const day = (n: number) => { const d = new Date(); d.setDate(d.getDate() - n); d.setHours(12, 0, 0, 0); return d.toISOString() }`,昨日=day(1)、旧=day(40)、今=day(0);正午锚点离日界 12h,任何运行时刻都稳。测试代码按此写。)

- [ ] **Step 2: 跑红** — `npx vitest run src/components/SessionList.test.tsx`(分组用例 FAIL,既有用例仍绿)。

- [ ] **Step 3: 实现** — SessionList.tsx:删 `current`/区头 div 与 `listAgents` 查询;`mine` 后加排序分组;ul 内改双层渲染:

```tsx
import { timeGroupLabel } from "../time"

const sorted = [...mine].sort((a, b) => +new Date(b.last_active_at) - +new Date(a.last_active_at))
const groups: { label: string; items: typeof sorted }[] = []
for (const s of sorted) {
  const label = timeGroupLabel(s.last_active_at)
  const last = groups[groups.length - 1]
  if (last?.label === label) last.items.push(s)
  else groups.push({ label, items: [s] })
}
```

```tsx
<ul className="min-h-0 flex-1 space-y-0.5 overflow-auto">
  {groups.map((g) => (
    <Fragment key={g.label}>
      <li aria-hidden className="px-1 pb-1 pt-3 text-[11px] font-medium tracking-wide text-slate-400 first:pt-0.5">
        {g.label}
      </li>
      {g.items.map((s) => (
        /* 原 li 行内容原样保留(改名 input / 标题按钮 / RowMenu) */
      ))}
    </Fragment>
  ))}
  {agentId && mine.length === 0 && (
    <li className="px-2 py-6 text-center text-xs text-slate-400">还没有对话</li>
  )}
  {!agentId && <li className="px-2 py-6 text-center text-xs text-slate-400">先选一个 agent</li>}
</ul>
```

(import `Fragment`;行 JSX 不改,只是搬进分组循环。外层 div 的 `min-h-0 flex-1` 保留。)

- [ ] **Step 4: 跑绿 + lint** — `npx vitest run src/components/SessionList.test.tsx && npm run lint`

- [ ] **Step 5: 提交** — `git commit -am "feat(frontend): session list time-grouped by last_active_at, header removed"`

---

## Task SR-5: AgentHeader(改名/设置/删除/autoRename)

**Files:** Create `src/components/AgentHeader.tsx`、`src/components/AgentHeader.test.tsx`

- [ ] **Step 1: 失败测试**(用例自 AgentList.test 迁移改造)

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { useStore } from "../store"
import { AgentHeader } from "./AgentHeader"

const A1 = { id: "a1", user_id: "u1", name: "main", model: "DeepSeek-V4-Pro", provider: "openai",
  thinking_level: null, enabled_tools: [], permissions: {}, key_ref: null }
let agents: (typeof A1)[]
const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>
)
const noAuto = { autoRenameId: null, onAutoRenameConsumed: () => {} }

beforeEach(() => {
  agents = [A1, { ...A1, id: "a2", name: "second" }]
  useStore.setState({ userId: "u1", agentId: "a1", sessionId: null })
  vi.spyOn(api, "listAgents").mockImplementation(() => Promise.resolve([...agents] as never))
})
afterEach(() => {
  useStore.setState({ userId: null, agentId: null, sessionId: null, settingsOpen: false })
  vi.restoreAllMocks()
})

describe("AgentHeader", () => {
  it("显示名字与模型;⚙ 打开 agent 设置", async () => {
    render(wrap(<AgentHeader {...noAuto} />))
    expect(await screen.findByText("main")).toBeInTheDocument()
    expect(screen.getByText("DeepSeek-V4-Pro")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "agent 设置" }))
    expect(useStore.getState().settingsOpen).toBe(true)
  })

  it("菜单重命名 → input → Enter 调 patchAgent;IME 回车不提交", async () => {
    const patch = vi.spyOn(api, "patchAgent").mockResolvedValue(A1 as never)
    render(wrap(<AgentHeader {...noAuto} />))
    await screen.findByText("main")
    fireEvent.click(screen.getByRole("button", { name: "main 更多操作" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "重命名" }))
    const input = await screen.findByDisplayValue("main")
    fireEvent.change(input, { target: { value: "我的" } })
    fireEvent.keyDown(input, { key: "Enter", isComposing: true })
    expect(patch).not.toHaveBeenCalled()
    fireEvent.keyDown(input, { key: "Enter" })
    await waitFor(() => expect(patch).toHaveBeenCalledWith("a1", { name: "我的" }))
  })

  it("删除两次点击;删当前选中落位到剩余第一个", async () => {
    const del = vi.spyOn(api, "deleteAgent").mockImplementation(() => {
      agents = agents.filter((a) => a.id !== "a1")
      return Promise.resolve()
    })
    render(wrap(<AgentHeader {...noAuto} />))
    await screen.findByText("main")
    fireEvent.click(screen.getByRole("button", { name: "main 更多操作" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "删除" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "连同全部会话删除?" }))
    await waitFor(() => expect(del).toHaveBeenCalledWith("a1"))
    await waitFor(() => expect(useStore.getState().agentId).toBe("a2"))
  })

  it("autoRenameId 命中当前 agent → 直接进入改名态并消费", async () => {
    const consumed = vi.fn()
    render(wrap(<AgentHeader autoRenameId="a1" onAutoRenameConsumed={consumed} />))
    expect(await screen.findByDisplayValue("main")).toBeInTheDocument()
    expect(consumed).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: 跑红** — 模块不存在。

- [ ] **Step 3: 实现 AgentHeader.tsx**(commitRename/removeAgent 逻辑自 AgentList 原样迁移)

```tsx
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Settings2 } from "lucide-react"
import { useEffect, useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"
import { RowMenu } from "./RowMenu"

/** 面板头部:当前 agent 名 + 模型;hover 出 ⚙(设置)与 …(重命名/删除)。
 * 改名态:行内 input;autoRenameId 命中当前 agent(rail 新建后)自动进入。 */
export function AgentHeader({
  autoRenameId,
  onAutoRenameConsumed,
}: {
  autoRenameId: string | null
  onAutoRenameConsumed: () => void
}) {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const setAgent = useStore((s) => s.setAgent)
  const openSettings = useStore((s) => s.openSettings)
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)

  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })
  const agent = agents.find((a) => a.id === agentId)

  useEffect(() => {
    if (autoRenameId && autoRenameId === agentId) {
      setEditing(true)
      onAutoRenameConsumed()
    }
  }, [autoRenameId, agentId, onAutoRenameConsumed])

  if (!agent) return null
  const invalidate = () => qc.invalidateQueries({ queryKey: ["agents", userId] })

  const commitRename = async (value: string) => {
    const name = value.trim()
    setEditing(false)
    if (!name || name === agent.name) return
    try {
      await api.patchAgent(agent.id, { name })
      await invalidate()
    } catch {
      // 改名失败:保持原名,不打断
    }
  }

  const removeAgent = async () => {
    await api.deleteAgent(agent.id) // 409 → RowMenu 原位提示
    await invalidate()
    await qc.invalidateQueries({ queryKey: ["sessions", userId] })
    if (useStore.getState().agentId === agent.id) {
      const fresh = qc.getQueryData<typeof agents>(["agents", userId]) ?? []
      const rest = fresh.filter((a) => a.id !== agent.id)
      setAgent(rest[0]?.id ?? null)
    }
  }

  return (
    <div className="group">
      {editing ? (
        <input
          autoFocus
          defaultValue={agent.name}
          maxLength={200}
          aria-label={`重命名 ${agent.name}`}
          onFocus={(e) => e.target.select()}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) void commitRename(e.currentTarget.value)
            else if (e.key === "Escape") setEditing(false)
          }}
          onBlur={() => setEditing(false)}
          className="w-full rounded-lg border border-brand-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
        />
      ) : (
        <div className="flex items-center gap-1">
          <span className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-800">{agent.name}</span>
          <button
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-slate-400 opacity-0 transition hover:bg-slate-100 hover:text-slate-700 group-hover:opacity-100"
            title="agent 设置"
            aria-label="agent 设置"
            onClick={() => openSettings()}
          >
            <Settings2 size={14} />
          </button>
          <RowMenu
            ariaLabel={`${agent.name} 更多操作`}
            items={[
              { label: "重命名", onSelect: () => setEditing(true) },
              { label: "删除", danger: true, confirmLabel: "连同全部会话删除?", onSelect: removeAgent },
            ]}
          />
        </div>
      )}
      <div className="truncate px-0.5 text-xs text-slate-400">{agent.model}</div>
    </div>
  )
}
```

(与 AgentList 差异:⚙ 不再 `setAgent`(本来就是当前);RowMenu 不传 `visible`(默认 hover 显形,头部常驻无选中态概念)。)

- [ ] **Step 4: 跑绿** — `npx vitest run src/components/AgentHeader.test.tsx`

- [ ] **Step 5: 提交** — `git add -A && git commit -m "feat(frontend): AgentHeader — rename/settings/delete moved to panel"`

---

## Task SR-6: Sidebar 重组 + 删 AgentList

**Files:** Modify `src/components/Sidebar.tsx`、`src/components/Sidebar.test.tsx`;Delete `src/components/AgentList.tsx`、`src/components/AgentList.test.tsx`

- [ ] **Step 1: 改 Sidebar 测试**(新契约:邮箱在菜单内、自动落位选最近活跃、品牌字标不再以文本常驻)

```tsx
it("renders rail + new-chat (disabled without an agent); email only inside account menu", () => {
  render(wrap(<Sidebar />))
  expect(screen.getByRole("button", { name: "新对话" })).toBeDisabled()
  expect(screen.queryByText("alice@example.com")).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "账户" }))
  expect(screen.getByText("alice@example.com")).toBeInTheDocument()
})

it("自动落位:agents 就绪选第一个,再选其【最近活跃】会话", async () => {
  vi.mocked(api.listAgents).mockResolvedValue([/* a1 同现状 fixture */] as never)
  const day = (n: number) => { const d = new Date(); d.setDate(d.getDate() - n); d.setHours(12, 0, 0, 0); return d.toISOString() }
  vi.mocked(api.listSessions).mockResolvedValue([
    { id: "s-old", user_id: "u1", agent_config_id: "a1", title: null, work_subdir: "workspace", last_active_at: day(3), last_context_tokens: null },
    { id: "s-new", user_id: "u1", agent_config_id: "a1", title: null, work_subdir: "workspace", last_active_at: day(0), last_context_tokens: null },
  ] as never)
  useStore.setState({ user: { id: "u1", email: "alice@example.com" }, userId: "u1", agentId: null, sessionId: null })
  render(wrap(<Sidebar />))
  await waitFor(() => expect(useStore.getState().agentId).toBe("a1"))
  await waitFor(() => expect(useStore.getState().sessionId).toBe("s-new")) // 非 created 序末尾
})
```

(自愈用例保留不动;vi.mock 的 api 需补 `createAgent: vi.fn()`、`logout: vi.fn()` 占位,因 AgentRail/AccountMenu 在 mock 模块下渲染。fireEvent import 补。)

- [ ] **Step 2: 跑红** — `npx vitest run src/components/Sidebar.test.tsx`

- [ ] **Step 3: 重写 Sidebar.tsx**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useEffect, useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"
import { AgentHeader } from "./AgentHeader"
import { AgentRail } from "./AgentRail"
import { SessionList } from "./SessionList"

export function Sidebar() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const sessionId = useStore((s) => s.sessionId)
  const setAgent = useStore((s) => s.setAgent)
  const setSession = useStore((s) => s.setSession)
  const qc = useQueryClient()
  // rail 新建 agent 后,面板头部要自动进入改名态(Sidebar 做两组件间的协调者)
  const [autoRenameId, setAutoRenameId] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () => api.createSession({ agent_config_id: agentId! }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["sessions", userId] })
      setSession(s.id)
    },
  })

  const agentsQ = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })
  const agents = agentsQ.data ?? []
  const { data: sessions = [] } = useQuery({
    queryKey: ["sessions", userId],
    queryFn: () => api.listSessions(),
    enabled: !!userId,
  })

  // 自动落位 + 自愈:注释与语义沿用现状,仅「最近一条」由 created 序末尾改为 last_active_at 最新
  useEffect(() => {
    if (!agentsQ.isSuccess) return
    if (!agentId && agents.length) setAgent(agents[0].id)
    else if (agentId && !agents.some((a) => a.id === agentId)) setAgent(agents[0]?.id ?? null)
  }, [agentId, agents, agentsQ.isSuccess, setAgent])
  useEffect(() => {
    if (!agentId || sessionId) return
    const mine = sessions
      .filter((s) => s.agent_config_id === agentId)
      .sort((a, b) => +new Date(b.last_active_at) - +new Date(a.last_active_at))
    if (mine.length) setSession(mine[0].id)
  }, [agentId, sessionId, sessions, setSession])

  return (
    <aside className="flex w-80 flex-none border-r border-slate-200">
      <AgentRail onCreated={setAutoRenameId} />
      <div className="flex min-w-0 flex-1 flex-col gap-3 bg-white/80 p-3 backdrop-blur-sm">
        {agentsQ.isSuccess && agents.length === 0 ? (
          <div className="flex flex-1 items-center justify-center px-4 text-center text-sm text-slate-400">
            在左栏 + 新建一个 Agent 开始
          </div>
        ) : (
          <>
            <AgentHeader autoRenameId={autoRenameId} onAutoRenameConsumed={() => setAutoRenameId(null)} />
            <button
              disabled={!agentId || create.isPending}
              onClick={() => create.mutate()}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand-50 px-3 py-2 text-sm font-medium text-brand-700 transition hover:bg-brand-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Plus size={16} />
              新对话
            </button>
            <SessionList />
          </>
        )}
      </div>
    </aside>
  )
}
```

然后 `git rm src/components/AgentList.tsx src/components/AgentList.test.tsx`。

- [ ] **Step 4: 全量跑绿 + lint** — `npm run lint && npm test`。预期连锁修复:任何引用 AgentList 的残留(grep 确认无);Sidebar 旧「Agent Cloud」文本断言已在 Step 1 移除。

- [ ] **Step 5: 提交** — `git add -A && git commit -m "feat(frontend): sidebar recomposed as agent rail + session panel"`

---

## Task SR-7: 全量回归 + preview 实景截图

- [ ] **Step 1:** `npm run lint && npm test` 全绿(40+ 文件)。
- [ ] **Step 2:** 起全栈 `bash scripts/dev_up.sh`(docker provisioner);preview 导航 `http://localhost:5173`,注册一次性账号(React 受控输入用原生 value setter + input 事件,见 feedback_preview_react_inputs),验证:rail 渲染/切换、新建 agent 进改名态、新对话置顶出现、时间分组、账户菜单;截图发用户。Docker 不可用则记录跳过原因,以 jsdom 结果为准。
- [ ] **Step 3:** 修复 preview 发现的问题(若有),提交。

## Task SR-8: Fable 5 对抗审查 + PR

- [ ] **Step 1:** 派 Fable 5 审查(model: fable):重点 = 浮层包含块(backdrop-blur/portal)、rail 滚动裁剪、autoRename 竞态(创建后切走)、自动落位与 setAgent 清会话的交互环、分组边界/时区、删除 agent 后的落位、a11y(aria-current/label)、测试是否空转。
- [ ] **Step 2:** TDD 修复审查问题,提交。
- [ ] **Step 3:** push + PR(标题 `feat(frontend): 侧栏重设计——Agent rail + 时间分组会话面板`,正文含诊断/方案/审查结论/测试统计);CI 绿后经用户确认合并。

---

## Self-Review

**Spec 覆盖:** 布局(SR-6 aside w-80 + rail 46px)✓;rail 规格(SR-2:缩写/配色/ring/portal tooltip/新建/账户槽,SR-3 账户)✓;面板(SR-5 头部改名⚙…,SR-6 主按钮,SR-4 分组列表/空态)✓;行为(SR-1 类型,SR-6 自动落位 last_active_at,自愈保留)✓;无 agent 空态(SR-6)✓;错误处理沿用(RowMenu/409,SR-5 迁移)✓;测试矩阵(各任务 + SR-7 回归)✓;范围外未引入 ✓。
**占位扫描:** SR-4 Step 3 行 JSX 标注「原样保留」并指明来源块(同文件搬移,非新写);SR-3 Step 3 标注保留的既有逻辑名(状态/doLogout);其余均完整代码。无 TBD。
**类型一致:** `AgentRail({ onCreated })`、`AgentHeader({ autoRenameId, onAutoRenameConsumed })` 在 SR-2/5/6 间一致;`timeGroupLabel(iso, now?)` 与测试一致;`Session.last_active_at: string` 全链路一致;`agentInitial/agentColor` 导出名与测试 import 一致。
