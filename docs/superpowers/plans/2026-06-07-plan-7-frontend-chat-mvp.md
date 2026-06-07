# 前端 Chat MVP 实现计划(Part 1:脚手架 + 契约 + 数据层)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tasks 5–8 在续写文件 `...-plan-7-frontend-chat-mvp-part2.md`。

**Goal:** 在 `frontend/` 建一个 React+Vite+TS 单页聊天应用,经 Vite 代理连后端,跑通「建/选 user+agent+session → 流式聊天(文本/思考/工具)→ 历史」。

**Architecture:** 纯前端 SPA,只连后端 REST+SSE;Vite dev 代理 `/api`→`localhost:8000`(后端零改动)。TanStack Query 管 REST,Zustand 管当前选择 + 流式回合状态,Tailwind(浅色 + teal)做样式。SSE 用 fetch 流式解析(非 EventSource)。

**Tech Stack:** React 18, Vite, TypeScript, TanStack Query v5, Zustand, Tailwind CSS, Vitest + React Testing Library。

**对应 spec:** `docs/superpowers/specs/2026-06-07-frontend-chat-mvp-design.md`。

---

## 测试 / 命令约定

- 前端命令都在 `frontend/` 下跑:`cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && <cmd>`。
- 单测:`npm test`(Vitest,run 模式:`npx vitest run`)。构建:`npm run build`(tsc + vite build)。Lint:`npm run lint`。
- 不需要 Docker / 后端在跑即可做单测与构建(组件/解析器用 mock)。
- 每条命令用绝对路径 `cd`(shell cwd 跨命令保持)。

## 文件结构(本计划全程)

```
frontend/
  package.json  vite.config.ts  tsconfig.json  tsconfig.node.json
  tailwind.config.js  postcss.config.js  index.html  .gitignore
  src/
    main.tsx  index.css  App.tsx  store.ts  types.ts
    api/client.ts  api/stream.ts  api/stream.test.ts
    components/ Sidebar.tsx UserBar.tsx AgentSelector.tsx SessionList.tsx
               ChatView.tsx MessageList.tsx MessageBubble.tsx
               ThinkingPanel.tsx ToolCallCard.tsx Composer.tsx
```

---

## Task 1: 脚手架 + 工具链

**Files:** 见各步(全部在 `frontend/` 下新建)。

- [ ] **Step 1: 用 Vite 建 React-TS 工程**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && npm create vite@latest . -- --template react-ts
```
若提示目录非空(有 `.gitkeep`),选择忽略/继续(保留 .gitkeep 无妨)。

- [ ] **Step 2: 装依赖**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && npm install && npm install @tanstack/react-query zustand && npm install -D tailwindcss@3 postcss autoprefixer vitest @testing-library/react @testing-library/jest-dom jsdom
```

- [ ] **Step 3: 初始化 Tailwind**

Create `frontend/tailwind.config.js`:
```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#f0fdfa", 100: "#ccfbf1", 200: "#99f6e4", 500: "#14b8a6",
          600: "#0d9488", 700: "#0f766e", 800: "#115e59",
        },
      },
    },
  },
  plugins: [],
}
```

Create `frontend/postcss.config.js`:
```js
export default { plugins: { tailwindcss: {}, autoprefixer: {} } }
```

Replace `frontend/src/index.css` with:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root { color-scheme: light; }
html, body, #root { height: 100%; }
body { margin: 0; background: #f8fafc; color: #0f172a; font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
```

- [ ] **Step 4: Vite 配置(代理 + vitest)**

Replace `frontend/vite.config.ts` with:
```ts
/// <reference types="vitest" />
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

const BACKEND = process.env.VITE_BACKEND_URL ?? "http://localhost:8000"

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // 浏览器同源:前端请求 /api/* 代理到后端;SSE 也透传
      "/api": { target: BACKEND, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
})
```

Create `frontend/src/test-setup.ts`:
```ts
import "@testing-library/jest-dom"
```

- [ ] **Step 5: package.json 脚本**

确保 `frontend/package.json` 的 `scripts` 含(合并进已有,勿删 vite 默认):
```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "lint": "tsc --noEmit",
    "test": "vitest run"
  }
}
```

- [ ] **Step 6: .gitignore**

Create `frontend/.gitignore`:
```
node_modules
dist
*.local
.vite
```

- [ ] **Step 7: 冒烟——构建通过**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && npm run build
```
Expected: tsc + vite build 成功,生成 `dist/`(默认模板能编过)。

- [ ] **Step 8: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add frontend && git commit -m "feat(frontend): scaffold React+Vite+TS with Tailwind, Vite /api proxy, Vitest"
```

---

## Task 2: 契约类型 + REST 客户端

**Files:**
- Create: `frontend/src/types.ts`
- Create: `frontend/src/api/client.ts`

- [ ] **Step 1: 写类型**

Create `frontend/src/types.ts`:
```ts
export interface User { id: string; email: string }
export interface AgentConfig {
  id: string; user_id: string; name: string; model: string; provider: string
  thinking_level: string | null; enabled_tools: string[]; permissions: Record<string, unknown>
}
export interface Session { id: string; user_id: string; agent_config_id: string; title: string | null; work_subdir: string }

export interface ToolCall { id: string; name: string; arguments: Record<string, unknown> }
export interface ToolResult { call_id: string; content: string; is_error: boolean }
export interface MessageContent { text: string; tool_calls: ToolCall[]; tool_results: ToolResult[] }
export interface Message { id: string; seq: number; role: "user" | "assistant" | "tool"; content: MessageContent }

// SSE 回合事件(后端 turn_event_to_sse 的形状)
export type TurnEvent =
  | { type: "text_delta"; text: string }
  | { type: "thinking_delta"; text: string }
  | { type: "tool_call_start"; call_id: string; tool: string; args: Record<string, unknown> }
  | { type: "tool_result"; call_id: string; result: string; is_error: boolean }
  | { type: "turn_done"; usage: { input_tokens: number; output_tokens: number }; message_ids: string[]; stop_reason: string }
  | { type: "error"; message: string; recoverable: boolean }
```

- [ ] **Step 2: 写 REST 客户端**

Create `frontend/src/api/client.ts`:
```ts
import type { AgentConfig, Message, Session, User } from "../types"

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    const body = await res.text().catch(() => "")
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

export const api = {
  createUser: (email: string) => http<User>("/users", { method: "POST", body: JSON.stringify({ email }) }),
  getUser: (id: string) => http<User>(`/users/${id}`),
  listAgents: (userId: string) => http<AgentConfig[]>(`/agent-configs?user_id=${userId}`),
  createAgent: (body: { user_id: string; name: string; model: string; provider: string }) =>
    http<AgentConfig>("/agent-configs", { method: "POST", body: JSON.stringify(body) }),
  listSessions: (userId: string) => http<Session[]>(`/sessions?user_id=${userId}`),
  createSession: (body: { user_id: string; agent_config_id: string; title?: string }) =>
    http<Session>("/sessions", { method: "POST", body: JSON.stringify(body) }),
  listMessages: (sessionId: string) => http<Message[]>(`/sessions/${sessionId}/messages`),
}
```

- [ ] **Step 3: 冒烟——类型编译**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && npm run lint
```
Expected: 无类型错误。

- [ ] **Step 4: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add frontend/src/types.ts frontend/src/api/client.ts && git commit -m "feat(frontend): backend contract types + typed REST client"
```

---

## Task 3: SSE 回合流解析器(TDD 核心)

**Files:**
- Create: `frontend/src/api/stream.ts`
- Test: `frontend/src/api/stream.test.ts`

- [ ] **Step 1: 写失败测试**

Create `frontend/src/api/stream.test.ts`:
```ts
import { describe, expect, it } from "vitest"
import { parseSSE } from "./stream"

function collect(chunks: string[]) {
  const events: unknown[] = []
  const parse = parseSSE((e) => events.push(e))
  for (const c of chunks) parse(c)
  return events
}

describe("parseSSE", () => {
  it("parses a single data line", () => {
    const events = collect(['data: {"type":"text_delta","text":"hi"}\n\n'])
    expect(events).toEqual([{ type: "text_delta", text: "hi" }])
  })

  it("handles an event split across chunks", () => {
    const events = collect(['data: {"type":"text_d', 'elta","text":"yo"}\n\n'])
    expect(events).toEqual([{ type: "text_delta", text: "yo" }])
  })

  it("parses multiple events and ignores blank lines", () => {
    const events = collect([
      'data: {"type":"thinking_delta","text":"hmm"}\n\n',
      'data: {"type":"tool_call_start","call_id":"c1","tool":"bash","args":{"command":"ls"}}\n\n',
      'data: {"type":"turn_done","usage":{"input_tokens":1,"output_tokens":2},"message_ids":["m1"],"stop_reason":"end_turn"}\n\n',
    ])
    expect(events.map((e) => (e as { type: string }).type)).toEqual([
      "thinking_delta", "tool_call_start", "turn_done",
    ])
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && npx vitest run src/api/stream.test.ts
```
Expected: FAIL（`parseSSE` 未定义）。

- [ ] **Step 3: 写解析器 + 流式请求**

Create `frontend/src/api/stream.ts`:
```ts
import type { TurnEvent } from "../types"

/** 把任意切分的 SSE 文本喂进来,逐个 data: 事件回调。返回一个 feed(chunk) 函数。 */
export function parseSSE(onEvent: (e: TurnEvent) => void): (chunk: string) => void {
  let buf = ""
  return (chunk: string) => {
    buf += chunk
    let sep: number
    // SSE 事件以空行(\n\n)分隔
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const block = buf.slice(0, sep)
      buf = buf.slice(sep + 2)
      for (const line of block.split("\n")) {
        const trimmed = line.trim()
        if (trimmed.startsWith("data:")) {
          const payload = trimmed.slice("data:".length).trim()
          if (payload) onEvent(JSON.parse(payload) as TurnEvent)
        }
      }
    }
  }
}

/** POST /turn/stream 并把 SSE 事件流式回调;返回可中断的 AbortController。 */
export function streamTurn(
  sessionId: string,
  content: string,
  onEvent: (e: TurnEvent) => void,
): { done: Promise<void>; abort: () => void } {
  const ctrl = new AbortController()
  const done = (async () => {
    const res = await fetch(`/api/sessions/${sessionId}/turn/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
      signal: ctrl.signal,
    })
    if (!res.ok || !res.body) {
      const body = await res.text().catch(() => "")
      throw new Error(`turn stream failed: ${res.status} ${body}`)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    const feed = parseSSE(onEvent)
    for (;;) {
      const { done: rdone, value } = await reader.read()
      if (rdone) break
      feed(decoder.decode(value, { stream: true }))
    }
  })()
  return { done, abort: () => ctrl.abort() }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && npx vitest run src/api/stream.test.ts
```
Expected: 3 passed。

- [ ] **Step 5: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add frontend/src/api/stream.ts frontend/src/api/stream.test.ts && git commit -m "feat(frontend): SSE turn-stream parser + streamTurn (fetch streaming)"
```

---

## Task 4: store + React Query + 应用根

**Files:**
- Create: `frontend/src/store.ts`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: 写 store**

Create `frontend/src/store.ts`:
```ts
import { create } from "zustand"
import type { ToolCall, ToolResult } from "./types"

// 进行中回合的实时聚合(由 SSE 事件填充)
export interface LiveTurn {
  thinking: string
  text: string
  toolCalls: { call: ToolCall; result?: ToolResult }[]
  status: "streaming" | "done" | "error"
  errorMessage?: string
}

interface AppState {
  userId: string | null
  agentId: string | null
  sessionId: string | null
  live: LiveTurn | null
  setUser: (id: string | null) => void
  setAgent: (id: string | null) => void
  setSession: (id: string | null) => void
  startLive: () => void
  setLive: (fn: (t: LiveTurn) => LiveTurn) => void
  clearLive: () => void
}

const EMPTY: LiveTurn = { thinking: "", text: "", toolCalls: [], status: "streaming" }

export const useStore = create<AppState>((set) => ({
  userId: localStorage.getItem("ac.userId"),
  agentId: null,
  sessionId: null,
  live: null,
  setUser: (id) => {
    if (id) localStorage.setItem("ac.userId", id)
    else localStorage.removeItem("ac.userId")
    set({ userId: id, agentId: null, sessionId: null })
  },
  setAgent: (id) => set({ agentId: id, sessionId: null }),
  setSession: (id) => set({ sessionId: id, live: null }),
  startLive: () => set({ live: { ...EMPTY, toolCalls: [] } }),
  setLive: (fn) => set((s) => (s.live ? { live: fn(s.live) } : {})),
  clearLive: () => set({ live: null }),
}))
```

- [ ] **Step 2: 应用根接 QueryClient**

Replace `frontend/src/main.tsx` with:
```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import App from "./App"
import "./index.css"

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
```

- [ ] **Step 3: 占位 App(下一组替换)**

Replace `frontend/src/App.tsx` with a minimal placeholder so构建通过:
```tsx
export default function App() {
  return <div className="p-6 text-slate-600">agent-cloud — loading…</div>
}
```
删除模板里 `src/App.css`(若存在)的 import(上面的 App.tsx 已不引用它)。

- [ ] **Step 4: 冒烟——构建 + 单测**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && npm run build && npx vitest run
```
Expected: 构建成功;stream 测试通过。

- [ ] **Step 5: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add frontend/src/store.ts frontend/src/main.tsx frontend/src/App.tsx && git commit -m "feat(frontend): zustand store + QueryClient root"
```

---

> **后续 Task 5–8(Sidebar/Chat 组件、设计打磨、dev_up.sh、收尾)见 `2026-06-07-plan-7-frontend-chat-mvp-part2.md`。**
