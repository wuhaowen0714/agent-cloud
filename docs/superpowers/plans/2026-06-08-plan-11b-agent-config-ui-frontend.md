# Plan 11b: Agent Config Management UI + Sidebar Redesign — Frontend

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** A right-side **settings drawer** (Agent | 技能 tabs) to edit agent basics + tools + AGENTS instructions + per-agent skills, and manage the skill pool; plus a **redesigned sidebar** (grouped, styled). Depends on Plan 11a (`GET /skills/registry`).

**Tech Stack:** React 19, TanStack Query, Zustand, Tailwind (light+teal), Vitest+RTL. Spec: [2026-06-08-agent-config-management-ui-design.md](../specs/2026-06-08-agent-config-management-ui-design.md).

---

## File Structure
- Modify: `types.ts` (Skill, ContextDocument), `api/client.ts` (config methods), `store.ts` (settingsOpen).
- Create: `agentConfig.ts` (+ test) — tool helpers (pure).
- Rewrite: `components/UserBar.tsx`, `components/AgentSelector.tsx`, `components/SessionList.tsx`, `components/Sidebar.tsx`.
- Create: `components/settings/SettingsDrawer.tsx`, `components/settings/AgentSettings.tsx`, `components/settings/SkillsPanel.tsx` (+ tests).
- Modify: `App.tsx` (render `<SettingsDrawer/>`).

---

## Task 1: types + api/client + store

- [ ] **Step 1: types**

`types.ts` add:
```typescript
export interface Skill { id: string; user_id: string; name: string; description: string; source: string; version: string }
export interface ContextDocument { id: string; scope: string; type: string; owner_id: string; content: string }
```

- [ ] **Step 2: api/client** — import `AgentConfig, ContextDocument, Skill` and add to `api`:
```typescript
  patchAgent: (id: string, body: Partial<Pick<AgentConfig, "name" | "model" | "provider" | "thinking_level" | "enabled_tools">>) =>
    http<AgentConfig>(`/agent-configs/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  listDocs: (scope: string, ownerId: string) =>
    http<ContextDocument[]>(`/context-documents?scope=${scope}&owner_id=${ownerId}`),
  putDoc: (scope: string, type: string, ownerId: string, content: string) =>
    http<ContextDocument>("/context-documents", { method: "PUT", body: JSON.stringify({ scope, type, owner_id: ownerId, content }) }),
  listSkills: (userId: string) => http<Skill[]>(`/skills?user_id=${userId}`),
  listRegistry: () => http<string[]>("/skills/registry"),
  installSkill: (userId: string, name: string) =>
    http<Skill>("/skills/install", { method: "POST", body: JSON.stringify({ user_id: userId, name }) }),
  deleteSkill: (id: string) => http<void>(`/skills/${id}`, { method: "DELETE" }),
  getAgentSkills: (agentId: string) => http<Skill[]>(`/agent-configs/${agentId}/skills`),
  setAgentSkills: (agentId: string, skillIds: string[]) =>
    http<Skill[]>(`/agent-configs/${agentId}/skills`, { method: "PUT", body: JSON.stringify({ skill_ids: skillIds }) }),
```

- [ ] **Step 3: store** — add `settingsOpen` + open/close; close on user switch.

In `AppState`: `settingsOpen: boolean`, `openSettings: () => void`, `closeSettings: () => void`.
In create body: `settingsOpen: false,` and
```typescript
  openSettings: () => set({ settingsOpen: true }),
  closeSettings: () => set({ settingsOpen: false }),
```
In `setUser`, add `settingsOpen: false` to the `set({...})` (switching user closes settings). (`setAgent` leaves `settingsOpen` as-is, so changing agent while the drawer is open re-renders it for the new agent.)

- [ ] **Step 4: lint + commit**

Run: `cd frontend && npm run -s lint` → exit 0.
```bash
git add frontend/src/types.ts frontend/src/api/client.ts frontend/src/store.ts
git commit -m "feat(frontend): config API client + types + settings drawer store flag"
```

---

## Task 2: tool helpers (pure)

- [ ] **Step 1: failing test** — `agentConfig.test.ts`:
```typescript
import { describe, expect, it } from "vitest"
import { BUILTIN_TOOLS, checkedToEnabled, enabledToChecked } from "./agentConfig"

describe("tool helpers", () => {
  it("empty enabled_tools means all checked", () => {
    expect(enabledToChecked([])).toEqual(new Set(BUILTIN_TOOLS.map((t) => t.name)))
  })
  it("a subset stays that subset", () => {
    expect(enabledToChecked(["bash"])).toEqual(new Set(["bash"]))
  })
  it("all checked normalizes to [] (= all)", () => {
    expect(checkedToEnabled(new Set(BUILTIN_TOOLS.map((t) => t.name)))).toEqual([])
  })
  it("a subset saves as that subset, in canonical order", () => {
    expect(checkedToEnabled(new Set(["read_file", "bash"]))).toEqual(["bash", "read_file"])
  })
})
```

- [ ] **Step 2: run → fail**, then implement `agentConfig.ts`:
```typescript
export const BUILTIN_TOOLS: { name: string; desc: string }[] = [
  { name: "bash", desc: "运行 shell 命令" },
  { name: "write_file", desc: "写文件" },
  { name: "read_file", desc: "读文件" },
]
const ALL = BUILTIN_TOOLS.map((t) => t.name)

// agent.enabled_tools → 勾选集合(空 = 全部)
export function enabledToChecked(enabled: string[]): Set<string> {
  return new Set(enabled.length ? enabled : ALL)
}
// 勾选集合 → 保存值:全勾规范化为 [](= 全部),子集保存子集(按内置顺序)
export function checkedToEnabled(checked: Set<string>): string[] {
  const list = ALL.filter((n) => checked.has(n))
  return list.length === ALL.length ? [] : list
}
```

- [ ] **Step 3: run → pass + commit**
```bash
git add frontend/src/agentConfig.ts frontend/src/agentConfig.test.ts
git commit -m "feat(frontend): tool enable/normalize helpers (test-first)"
```

---

## Task 3: Sidebar redesign

- [ ] **Step 1: UserBar** (`components/UserBar.tsx`) — restyle the signed-in chip (keep the email-form branch as-is, only restyle the chip):
```tsx
  if (userId) {
    return (
      <div className="flex items-center gap-2 text-sm">
        <span className="h-2 w-2 shrink-0 rounded-full bg-brand-500" />
        <span className="min-w-0 flex-1 truncate text-slate-600">{user?.email ?? userId}</span>
        <button className="shrink-0 text-xs text-slate-400 hover:text-slate-700" onClick={() => setUser(null)}>
          切换
        </button>
      </div>
    )
  }
```
(The `!userId` form branch is unchanged.)

- [ ] **Step 2: AgentSelector** (`components/AgentSelector.tsx`) — replace the whole component (drop the inline create form; add ⚙ + ＋ that drive the settings drawer):
```tsx
import { useQuery } from "@tanstack/react-query"
import { api } from "../api/client"
import { useStore } from "../store"

export function AgentSelector() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const setAgent = useStore((s) => s.setAgent)
  const openSettings = useStore((s) => s.openSettings)

  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(userId!),
    enabled: !!userId,
  })

  if (!userId) return null
  return (
    <div className="flex items-center gap-1.5">
      <select
        className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
        value={agentId ?? ""}
        onChange={(e) => setAgent(e.target.value || null)}
      >
        <option value="">选择 agent…</option>
        {agents.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name} · {a.model}
          </option>
        ))}
      </select>
      <button
        className="shrink-0 rounded border border-slate-200 px-2 py-1 text-sm text-slate-500 hover:bg-slate-50 disabled:opacity-40"
        title="agent 设置"
        disabled={!agentId}
        onClick={openSettings}
      >
        ⚙
      </button>
      <button
        className="shrink-0 rounded border border-slate-200 px-2 py-1 text-sm text-slate-500 hover:bg-slate-50"
        title="新建 agent"
        onClick={() => {
          setAgent(null)
          openSettings()
        }}
      >
        ＋
      </button>
    </div>
  )
}
```

- [ ] **Step 3: SessionList** (`components/SessionList.tsx`) — restyle (friendly titles, teal active, "新会话" in the section header). Replace the returned JSX:
```tsx
  if (!userId) return null
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-400">会话</span>
        <button
          className="rounded px-1.5 py-0.5 text-xs text-brand-700 enabled:hover:bg-brand-50 disabled:opacity-40"
          disabled={!agentId}
          title={agentId ? "" : "先选/建一个 agent"}
          onClick={() => create.mutate()}
        >
          ＋ 新会话
        </button>
      </div>
      <ul className="min-h-0 flex-1 space-y-0.5 overflow-auto">
        {sessions.map((s) => (
          <li key={s.id}>
            <button
              className={`w-full truncate rounded-md px-2 py-1.5 text-left text-sm ${
                s.id === sessionId
                  ? "bg-brand-50 font-medium text-brand-800 ring-1 ring-brand-100"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
              onClick={() => setSession(s.id)}
            >
              {s.title ?? `会话 ${s.id.slice(0, 6)}`}
            </button>
          </li>
        ))}
        {sessions.length === 0 && (
          <li className="px-2 py-1 text-xs text-slate-400">还没有会话</li>
        )}
      </ul>
    </div>
  )
```

- [ ] **Step 4: Sidebar** (`components/Sidebar.tsx`) — grouped layout with section labels:
```tsx
import { AgentSelector } from "./AgentSelector"
import { FileButton } from "./files/FileButton"
import { SessionList } from "./SessionList"
import { UserBar } from "./UserBar"

function Label({ children }: { children: string }) {
  return <div className="text-xs font-medium uppercase tracking-wide text-slate-400">{children}</div>
}

export function Sidebar() {
  return (
    <aside className="flex w-72 flex-col gap-3 border-r border-slate-200 bg-white p-3">
      <div className="text-sm font-semibold text-slate-800">agent-cloud</div>
      <UserBar />
      <div className="space-y-1.5">
        <Label>Agent</Label>
        <AgentSelector />
      </div>
      <div className="space-y-1.5">
        <Label>工作区</Label>
        <FileButton />
      </div>
      <div className="border-t border-slate-100" />
      <SessionList />
    </aside>
  )
}
```

- [ ] **Step 5: lint + commit** (`npm run -s lint` exit 0)
```bash
git add frontend/src/components/UserBar.tsx frontend/src/components/AgentSelector.tsx frontend/src/components/SessionList.tsx frontend/src/components/Sidebar.tsx
git commit -m "feat(frontend): redesign sidebar (grouped sections, agent settings entry, styled sessions)"
```

---

## Task 4: SettingsDrawer + AgentSettings

- [ ] **Step 1: SettingsDrawer** (`components/settings/SettingsDrawer.tsx`):
```tsx
import { useState } from "react"
import { useStore } from "../../store"
import { AgentSettings } from "./AgentSettings"
import { SkillsPanel } from "./SkillsPanel"

export function SettingsDrawer() {
  const open = useStore((s) => s.settingsOpen)
  const close = useStore((s) => s.closeSettings)
  const userId = useStore((s) => s.userId)
  const [tab, setTab] = useState<"agent" | "skills">("agent")
  if (!open || !userId) return null
  const tabCls = (t: string) =>
    `px-3 py-1.5 text-sm ${tab === t ? "border-b-2 border-brand-500 font-medium text-brand-700" : "text-slate-500 hover:text-slate-700"}`
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20" onClick={close} />
      <aside className="fixed right-0 top-0 z-50 flex h-full w-[30rem] max-w-[92vw] flex-col border-l border-slate-200 bg-white shadow-xl">
        <header className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
          <span className="text-sm font-semibold text-slate-800">设置</span>
          <button className="text-slate-400 hover:text-slate-700" onClick={close}>✕</button>
        </header>
        <div className="flex border-b border-slate-100">
          <button className={tabCls("agent")} onClick={() => setTab("agent")}>Agent</button>
          <button className={tabCls("skills")} onClick={() => setTab("skills")}>技能</button>
        </div>
        <div className="flex-1 overflow-auto p-3">
          {tab === "agent" ? <AgentSettings /> : <SkillsPanel />}
        </div>
      </aside>
    </>
  )
}
```

- [ ] **Step 2: AgentSettings** (`components/settings/AgentSettings.tsx`):
```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { api } from "../../api/client"
import { BUILTIN_TOOLS, checkedToEnabled, enabledToChecked } from "../../agentConfig"
import { useStore } from "../../store"

export function AgentSettings() {
  const userId = useStore((s) => s.userId)!
  const agentId = useStore((s) => s.agentId)
  const setAgent = useStore((s) => s.setAgent)
  const qc = useQueryClient()

  // 新建模式:没有选中 agent
  const [draft, setDraft] = useState({ name: "", model: "", provider: "openai" })
  const createAgent = useMutation({
    mutationFn: () => api.createAgent({ user_id: userId, ...draft }),
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["agents", userId] })
      setAgent(a.id)
    },
  })

  if (!agentId) {
    return (
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (draft.name && draft.model) createAgent.mutate()
        }}
      >
        <div className="text-sm font-medium text-slate-700">新建 Agent</div>
        {(["name", "model", "provider"] as const).map((k) => (
          <input
            key={k}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
            placeholder={k === "model" ? "model(如 DeepSeek-V4-Pro)" : k}
            value={draft[k]}
            onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
          />
        ))}
        <button className="rounded bg-brand-600 px-3 py-1 text-sm text-white hover:bg-brand-700">
          创建
        </button>
      </form>
    )
  }
  return <AgentEditor key={agentId} agentId={agentId} userId={userId} />
}

function AgentEditor({ agentId, userId }: { agentId: string; userId: string }) {
  const qc = useQueryClient()
  const { data: agents = [] } = useQuery({ queryKey: ["agents", userId], queryFn: () => api.listAgents(userId) })
  const agent = agents.find((a) => a.id === agentId)
  const { data: docs = [] } = useQuery({ queryKey: ["docs", "agent", agentId], queryFn: () => api.listDocs("agent", agentId) })
  const { data: pool = [] } = useQuery({ queryKey: ["skills", userId], queryFn: () => api.listSkills(userId) })
  const { data: enabled = [] } = useQuery({ queryKey: ["agentSkills", agentId], queryFn: () => api.getAgentSkills(agentId) })

  const [form, setForm] = useState({ name: "", model: "", provider: "", thinking_level: "" })
  const [tools, setTools] = useState<Set<string>>(new Set())
  const [instructions, setInstructions] = useState("")
  const [skillIds, setSkillIds] = useState<Set<string>>(new Set())
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (agent)
      setForm({ name: agent.name, model: agent.model, provider: agent.provider, thinking_level: agent.thinking_level ?? "" })
    if (agent) setTools(enabledToChecked(agent.enabled_tools))
  }, [agent])
  useEffect(() => {
    setInstructions(docs.find((d) => d.type === "AGENTS")?.content ?? "")
  }, [docs])
  useEffect(() => {
    setSkillIds(new Set(enabled.map((s) => s.id)))
  }, [enabled])

  const save = useMutation({
    mutationFn: async () => {
      await api.patchAgent(agentId, { ...form, enabled_tools: checkedToEnabled(tools) })
      if (instructions.trim()) await api.putDoc("agent", "AGENTS", agentId, instructions)
      await api.setAgentSkills(agentId, [...skillIds])
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents", userId] })
      qc.invalidateQueries({ queryKey: ["agentSkills", agentId] })
      qc.invalidateQueries({ queryKey: ["docs", "agent", agentId] })
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    },
  })

  const toggle = (set: Set<string>, key: string) => {
    const n = new Set(set)
    n.has(key) ? n.delete(key) : n.add(key)
    return n
  }
  const field = "w-full rounded border border-slate-300 px-2 py-1 text-sm"

  return (
    <div className="space-y-4 text-sm">
      <div className="space-y-2">
        <input className={field} value={form.name} placeholder="名称" onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <input className={field} value={form.model} placeholder="模型" onChange={(e) => setForm({ ...form, model: e.target.value })} />
        <input className={field} value={form.provider} placeholder="provider" onChange={(e) => setForm({ ...form, provider: e.target.value })} />
        <select className={field} value={form.thinking_level} onChange={(e) => setForm({ ...form, thinking_level: e.target.value })}>
          <option value="">思考档位:默认</option>
          <option value="low">low</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
        </select>
      </div>

      <div className="space-y-1">
        <div className="font-medium text-slate-700">工具</div>
        {BUILTIN_TOOLS.map((t) => (
          <label key={t.name} className="flex items-center gap-2 text-slate-600">
            <input type="checkbox" checked={tools.has(t.name)} onChange={() => setTools((s) => toggle(s, t.name))} />
            <span className="font-mono text-xs">{t.name}</span>
            <span className="text-xs text-slate-400">{t.desc}</span>
          </label>
        ))}
      </div>

      <div className="space-y-1">
        <div className="font-medium text-slate-700">指令(AGENTS)</div>
        <textarea
          className="h-32 w-full resize-none rounded border border-slate-300 px-2 py-1 font-mono text-xs"
          placeholder="给这个 agent 的指令/人设(可选)"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
        />
      </div>

      <div className="space-y-1">
        <div className="font-medium text-slate-700">启用技能</div>
        {pool.length === 0 ? (
          <div className="text-xs text-slate-400">技能池为空 — 去"技能"页安装</div>
        ) : (
          pool.map((sk) => (
            <label key={sk.id} className="flex items-center gap-2 text-slate-600">
              <input type="checkbox" checked={skillIds.has(sk.id)} onChange={() => setSkillIds((s) => toggle(s, sk.id))} />
              <span className="text-xs">{sk.name}</span>
              <span className="truncate text-xs text-slate-400">{sk.description}</span>
            </label>
          ))
        )}
      </div>

      <div className="flex items-center gap-2">
        <button
          className="rounded bg-brand-600 px-4 py-1.5 text-sm text-white hover:bg-brand-700 disabled:opacity-40"
          disabled={save.isPending}
          onClick={() => save.mutate()}
        >
          {save.isPending ? "保存中…" : "保存"}
        </button>
        {saved && <span className="text-xs text-brand-600">已保存</span>}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: lint** (`npm run -s lint`). Note: `SkillsPanel` must exist for SettingsDrawer to compile — do Task 5 before lint, or stub it. (Recommended: implement Task 5 next, then lint both.)

---

## Task 5: SkillsPanel (技能 tab)

- [ ] **Step 1: SkillsPanel** (`components/settings/SkillsPanel.tsx`):
```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "../../api/client"
import { useStore } from "../../store"

export function SkillsPanel() {
  const userId = useStore((s) => s.userId)!
  const qc = useQueryClient()
  const [pick, setPick] = useState("")

  const { data: pool = [] } = useQuery({ queryKey: ["skills", userId], queryFn: () => api.listSkills(userId) })
  const { data: registry = [] } = useQuery({ queryKey: ["registry"], queryFn: () => api.listRegistry() })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["skills", userId] })
    qc.invalidateQueries({ queryKey: ["agentSkills"] })
  }
  const install = useMutation({ mutationFn: (name: string) => api.installSkill(userId, name), onSuccess: () => { setPick(""); refresh() } })
  const remove = useMutation({ mutationFn: (id: string) => api.deleteSkill(id), onSuccess: refresh })

  const installed = new Set(pool.map((s) => s.name))
  const available = registry.filter((n) => !installed.has(n))

  return (
    <div className="space-y-4 text-sm">
      <div className="space-y-1">
        <div className="font-medium text-slate-700">已安装</div>
        {pool.length === 0 && <div className="text-xs text-slate-400">还没有安装技能</div>}
        {pool.map((sk) => (
          <div key={sk.id} className="flex items-center gap-2 rounded border border-slate-200 px-2 py-1">
            <span className="min-w-0 flex-1">
              <span className="text-slate-700">{sk.name}</span>
              <span className="ml-2 truncate text-xs text-slate-400">{sk.description}</span>
            </span>
            <button className="shrink-0 text-xs text-slate-400 hover:text-red-600" onClick={() => remove.mutate(sk.id)}>
              删除
            </button>
          </div>
        ))}
      </div>
      <div className="space-y-1">
        <div className="font-medium text-slate-700">从 registry 安装</div>
        <div className="flex gap-2">
          <select className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 text-sm" value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">选择技能…</option>
            {available.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
          <button
            className="shrink-0 rounded bg-brand-600 px-3 py-1 text-sm text-white hover:bg-brand-700 disabled:opacity-40"
            disabled={!pick || install.isPending}
            onClick={() => install.mutate(pick)}
          >
            安装
          </button>
        </div>
        {available.length === 0 && registry.length > 0 && <div className="text-xs text-slate-400">registry 里的技能都装好了</div>}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: wire into App** (`App.tsx`) — render `<SettingsDrawer/>` alongside `<FileDrawer/>`:
```tsx
import { ChatView } from "./components/ChatView"
import { FileDrawer } from "./components/files/FileDrawer"
import { SettingsDrawer } from "./components/settings/SettingsDrawer"
import { Sidebar } from "./components/Sidebar"

export default function App() {
  return (
    <div className="flex h-full">
      <Sidebar />
      <main className="flex min-w-0 flex-1 flex-col bg-slate-50">
        <ChatView />
      </main>
      <FileDrawer />
      <SettingsDrawer />
    </div>
  )
}
```

- [ ] **Step 3: lint + commit**

Run: `cd frontend && npm run -s lint` → exit 0.
```bash
git add frontend/src/components/settings/ frontend/src/App.tsx
git commit -m "feat(frontend): settings drawer (Agent settings + skills) wired into app"
```

---

## Task 6: component tests + regression + live verify

- [ ] **Step 1: tests** — `components/settings/AgentSettings.test.tsx` (create-mode form + tool checkbox reflects enabled_tools) and `components/settings/SkillsPanel.test.tsx` (install picker filters installed). Use a `QueryClientProvider` wrapper and `vi.mock("../../api/client")` or seed the query cache; assert: BUILTIN_TOOLS render, an unchecked tool toggles, the registry picker excludes installed names. (Keep these focused — the heavy save flow is covered by live verify.)

Minimal example for the tool-render assertion:
```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it } from "vitest"
import { BUILTIN_TOOLS } from "../../agentConfig"
import { SkillsPanel } from "./SkillsPanel"
// (AgentSettings needs store agentId + queries; prefer testing agentConfig.ts purely +
//  SkillsPanel rendering. Set localStorage ac.userId before render.)

const wrap = (ui: ReactNode) => <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>

describe("SkillsPanel", () => {
  it("renders without crashing and shows the install section", () => {
    localStorage.setItem("ac.userId", "u1")
    render(wrap(<SkillsPanel />))
    expect(screen.getByText("从 registry 安装")).toBeInTheDocument()
  })
})
```
(Keep `agentConfig.test.ts` from Task 2 as the core logic coverage; component tests are smoke-level.)

- [ ] **Step 2: full frontend regression**

Run: `cd frontend && npm run -s lint && npm run -s test` → tsc exit 0; all suites pass.

- [ ] **Step 3: commit**
```bash
git add frontend/src/components/settings/*.test.tsx
git commit -m "test(frontend): settings panels smoke tests"
```

- [ ] **Step 4: live verify** (after stack restart so backend has `/skills/registry`): open the redesigned sidebar; ⚙ → edit model/tools/instructions → 保存 → reopen, confirm persisted; 技能 tab → install `example-greeting` → Agent tab → enable it → 保存. Check `preview_console_logs` clean + screenshot the sidebar + settings drawer.

---

## Self-Review
- **Spec coverage:** settings drawer Agent(basics+tools+instructions+skill-enable) ✓; 技能(pool install/delete) ✓; sidebar redesign (grouped, ⚙/＋, styled sessions) ✓; store settingsOpen ✓; api methods ✓; enabled_tools empty=all via helpers ✓.
- **Consistency:** `openSettings`/`closeSettings`/`settingsOpen` used across store/sidebar/drawer; query keys `["agents",userId]`/`["skills",userId]`/`["agentSkills",agentId]`/`["docs","agent",agentId]` consistent between loaders and invalidations; `AgentEditor` keyed by `agentId` so switching agents resets local state.
- **No placeholders:** full component code + commands. (Task 4 lint deferred until Task 5 provides SkillsPanel — noted.)
- **Out of scope:** permissions, zip upload, memory UI.
