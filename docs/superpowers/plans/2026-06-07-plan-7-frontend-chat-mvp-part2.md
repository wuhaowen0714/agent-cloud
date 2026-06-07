# 前端 Chat MVP 实现计划(Part 2:UI + 设计 + 跑起来)

> 接 `2026-06-07-plan-7-frontend-chat-mvp.md`。同样所有前端命令在 `frontend/` 下、用绝对路径 `cd`;单测 `npx vitest run`,构建 `npm run build`。组件用 Tailwind(浅色 + `brand`=teal,见 Part1 Task1 的 tailwind.config)。

---

## Task 5: 侧栏(user / agent / 会话)

**Files (create):** `frontend/src/components/{UserBar,AgentSelector,SessionList,Sidebar}.tsx`

- [ ] **Step 1: UserBar**

Create `frontend/src/components/UserBar.tsx`:
```tsx
import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"

export function UserBar() {
  const userId = useStore((s) => s.userId)
  const setUser = useStore((s) => s.setUser)
  const [email, setEmail] = useState("")

  const { data: user } = useQuery({
    queryKey: ["user", userId],
    queryFn: () => api.getUser(userId!),
    enabled: !!userId,
  })

  if (userId) {
    return (
      <div className="flex items-center justify-between text-sm">
        <span className="truncate text-slate-600">{user?.email ?? userId}</span>
        <button className="text-slate-400 hover:text-slate-700" onClick={() => setUser(null)}>
          切换
        </button>
      </div>
    )
  }

  return (
    <form
      className="flex gap-2"
      onSubmit={async (e) => {
        e.preventDefault()
        if (!email.trim()) return
        const u = await api.createUser(email.trim())
        setUser(u.id)
      }}
    >
      <input
        className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
        placeholder="email 建/用 user"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <button className="rounded bg-brand-600 px-3 py-1 text-sm text-white hover:bg-brand-700">
        进入
      </button>
    </form>
  )
}
```

- [ ] **Step 2: AgentSelector(含新建)**

Create `frontend/src/components/AgentSelector.tsx`:
```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"

export function AgentSelector() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const setAgent = useStore((s) => s.setAgent)
  const qc = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ name: "", model: "", provider: "openai" })

  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(userId!),
    enabled: !!userId,
  })

  const create = useMutation({
    mutationFn: () => api.createAgent({ user_id: userId!, ...form }),
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["agents", userId] })
      setAgent(a.id)
      setCreating(false)
      setForm({ name: "", model: "", provider: "openai" })
    },
  })

  if (!userId) return null
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <select
          className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
          value={agentId ?? ""}
          onChange={(e) => setAgent(e.target.value || null)}
        >
          <option value="">选择 agent…</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>{a.name} · {a.model}</option>
          ))}
        </select>
        <button className="text-sm text-brand-700 hover:underline" onClick={() => setCreating((v) => !v)}>
          {creating ? "取消" : "+ 新建"}
        </button>
      </div>
      {creating && (
        <form
          className="space-y-1 rounded border border-slate-200 bg-white p-2"
          onSubmit={(e) => { e.preventDefault(); if (form.name && form.model) create.mutate() }}
        >
          {(["name", "model", "provider"] as const).map((k) => (
            <input
              key={k}
              className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
              placeholder={k === "model" ? "model(如 DeepSeek-V4-pro)" : k}
              value={form[k]}
              onChange={(e) => setForm({ ...form, [k]: e.target.value })}
            />
          ))}
          <button className="w-full rounded bg-brand-600 px-2 py-1 text-sm text-white hover:bg-brand-700">
            创建 agent
          </button>
        </form>
      )}
    </div>
  )
}
```

- [ ] **Step 3: SessionList(含新建)**

Create `frontend/src/components/SessionList.tsx`:
```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "../api/client"
import { useStore } from "../store"

export function SessionList() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const sessionId = useStore((s) => s.sessionId)
  const setSession = useStore((s) => s.setSession)
  const qc = useQueryClient()

  const { data: sessions = [] } = useQuery({
    queryKey: ["sessions", userId],
    queryFn: () => api.listSessions(userId!),
    enabled: !!userId,
  })

  const create = useMutation({
    mutationFn: () => api.createSession({ user_id: userId!, agent_config_id: agentId! }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["sessions", userId] })
      setSession(s.id)
    },
  })

  if (!userId) return null
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <button
        className="mb-2 rounded border border-brand-600 px-2 py-1 text-sm text-brand-700 enabled:hover:bg-brand-50 disabled:opacity-40"
        disabled={!agentId}
        title={agentId ? "" : "先选/建一个 agent"}
        onClick={() => create.mutate()}
      >
        + 新会话
      </button>
      <ul className="min-h-0 flex-1 space-y-1 overflow-auto">
        {sessions.map((s) => (
          <li key={s.id}>
            <button
              className={`w-full truncate rounded px-2 py-1 text-left text-sm ${
                s.id === sessionId ? "bg-brand-100 text-brand-800" : "text-slate-600 hover:bg-slate-100"
              }`}
              onClick={() => setSession(s.id)}
            >
              {s.title ?? s.id.slice(0, 8)}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
```

- [ ] **Step 4: Sidebar**

Create `frontend/src/components/Sidebar.tsx`:
```tsx
import { AgentSelector } from "./AgentSelector"
import { SessionList } from "./SessionList"
import { UserBar } from "./UserBar"

export function Sidebar() {
  return (
    <aside className="flex w-72 flex-col gap-3 border-r border-slate-200 bg-white p-3">
      <div className="text-sm font-semibold text-slate-800">agent-cloud</div>
      <UserBar />
      <AgentSelector />
      <div className="border-t border-slate-100" />
      <SessionList />
    </aside>
  )
}
```

- [ ] **Step 5: 冒烟编译**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && npm run lint
```
Expected: 无类型错误。

- [ ] **Step 6: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add frontend/src/components && git commit -m "feat(frontend): sidebar — user / agent / session selectors"
```

---

## Task 6: 聊天区(流式渲染)+ 组件测试

**Files (create):** `frontend/src/components/{ThinkingPanel,ToolCallCard,MessageBubble,MessageList,Composer,ChatView}.tsx`、`frontend/src/components/MessageBubble.test.tsx`;Modify `frontend/src/App.tsx`

- [ ] **Step 1: ThinkingPanel**

Create `frontend/src/components/ThinkingPanel.tsx`:
```tsx
import { useState } from "react"

export function ThinkingPanel({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  if (!text) return null
  return (
    <div className="mt-1 text-xs">
      <button className="text-slate-400 hover:text-slate-600" onClick={() => setOpen((v) => !v)}>
        {open ? "▾ 思考" : "▸ 思考"}
      </button>
      {open && (
        <pre className="mt-1 whitespace-pre-wrap rounded bg-slate-50 p-2 font-mono text-slate-500">
          {text}
        </pre>
      )}
    </div>
  )
}
```

- [ ] **Step 2: ToolCallCard**

Create `frontend/src/components/ToolCallCard.tsx`:
```tsx
import type { ToolCall, ToolResult } from "../types"

export function ToolCallCard({ call, result }: { call: ToolCall; result?: ToolResult }) {
  return (
    <div className="my-1 rounded border border-slate-200 bg-slate-50 p-2 text-xs">
      <div className="font-mono text-slate-700">
        🔧 {call.name}({JSON.stringify(call.arguments)})
      </div>
      {result && (
        <pre
          className={`mt-1 whitespace-pre-wrap font-mono ${
            result.is_error ? "text-red-600" : "text-slate-500"
          }`}
        >
          {result.is_error ? "[error] " : "→ "}
          {result.content}
        </pre>
      )}
    </div>
  )
}
```

- [ ] **Step 3: MessageBubble**

Create `frontend/src/components/MessageBubble.tsx`:
```tsx
import type { Message } from "../types"
import { ToolCallCard } from "./ToolCallCard"

export function MessageBubble({ message }: { message: Message }) {
  const { role, content } = message
  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl bg-brand-600 px-3 py-2 text-sm text-white">
          {content.text}
        </div>
      </div>
    )
  }
  if (role === "tool") {
    return (
      <div className="flex justify-start">
        <div className="max-w-[80%]">
          {content.tool_results.map((r) => (
            <ToolCallCard key={r.call_id} call={{ id: r.call_id, name: "result", arguments: {} }} result={r} />
          ))}
        </div>
      </div>
    )
  }
  // assistant
  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] rounded-2xl bg-white px-3 py-2 text-sm text-slate-800 shadow-sm ring-1 ring-slate-200">
        {content.text && <div className="whitespace-pre-wrap">{content.text}</div>}
        {content.tool_calls.map((c) => (
          <ToolCallCard key={c.id} call={c} />
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: 组件测试(先写,验证渲染)**

Create `frontend/src/components/MessageBubble.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import type { Message } from "../types"
import { MessageBubble } from "./MessageBubble"

const mk = (over: Partial<Message>): Message => ({
  id: "m", seq: 0, role: "assistant",
  content: { text: "", tool_calls: [], tool_results: [] }, ...over,
})

describe("MessageBubble", () => {
  it("renders user text", () => {
    render(<MessageBubble message={mk({ role: "user", content: { text: "hello", tool_calls: [], tool_results: [] } })} />)
    expect(screen.getByText("hello")).toBeInTheDocument()
  })

  it("renders assistant tool call", () => {
    render(<MessageBubble message={mk({ content: { text: "ok", tool_calls: [{ id: "c1", name: "bash", arguments: { command: "ls" } }], tool_results: [] } })} />)
    expect(screen.getByText(/bash/)).toBeInTheDocument()
  })

  it("marks errored tool result", () => {
    render(<MessageBubble message={mk({ role: "tool", content: { text: "", tool_calls: [], tool_results: [{ call_id: "c1", content: "boom", is_error: true }] } })} />)
    expect(screen.getByText(/\[error\]/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 5: 跑测试确认通过**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && npx vitest run src/components/MessageBubble.test.tsx
```
Expected: 3 passed（组件已在上面实现,应直接过）。

- [ ] **Step 6: Composer**

Create `frontend/src/components/Composer.tsx`:
```tsx
import { useState } from "react"

export function Composer({ disabled, onSend }: { disabled: boolean; onSend: (text: string) => void }) {
  const [text, setText] = useState("")
  const send = () => {
    const t = text.trim()
    if (!t || disabled) return
    onSend(t)
    setText("")
  }
  return (
    <div className="flex gap-2 border-t border-slate-200 bg-white p-3">
      <textarea
        className="min-h-[44px] flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
        placeholder={disabled ? "生成中…" : "说点什么(Enter 发送,Shift+Enter 换行)"}
        rows={1}
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send() }
        }}
      />
      <button
        className="rounded-lg bg-brand-600 px-4 text-sm text-white enabled:hover:bg-brand-700 disabled:opacity-40"
        disabled={disabled}
        onClick={send}
      >
        发送
      </button>
    </div>
  )
}
```

- [ ] **Step 7: MessageList(历史 + 进行中回合)**

Create `frontend/src/components/MessageList.tsx`:
```tsx
import { useEffect, useRef } from "react"
import { useStore } from "../store"
import type { Message } from "../types"
import { MessageBubble } from "./MessageBubble"
import { ThinkingPanel } from "./ThinkingPanel"
import { ToolCallCard } from "./ToolCallCard"

export function MessageList({ messages }: { messages: Message[] }) {
  const live = useStore((s) => s.live)
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }) }, [messages, live])

  return (
    <div className="flex-1 space-y-3 overflow-auto p-4">
      {messages.map((m) => <MessageBubble key={m.id} message={m} />)}
      {live && (
        <div className="flex justify-start">
          <div className="max-w-[80%] rounded-2xl bg-white px-3 py-2 text-sm text-slate-800 shadow-sm ring-1 ring-slate-200">
            <ThinkingPanel text={live.thinking} />
            {live.toolCalls.map((tc) => <ToolCallCard key={tc.call.id} call={tc.call} result={tc.result} />)}
            {live.text && <div className="whitespace-pre-wrap">{live.text}</div>}
            {live.status === "streaming" && <span className="ml-0.5 animate-pulse text-brand-600">▍</span>}
            {live.status === "error" && (
              <div className="mt-1 text-xs text-red-600">⚠ {live.errorMessage ?? "回合失败"},可重试。</div>
            )}
          </div>
        </div>
      )}
      <div ref={endRef} />
    </div>
  )
}
```

- [ ] **Step 8: ChatView(编排 streamTurn)**

Create `frontend/src/components/ChatView.tsx`:
```tsx
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "../api/client"
import { streamTurn } from "../api/stream"
import { useStore } from "../store"
import { Composer } from "./Composer"
import { MessageList } from "./MessageList"

export function ChatView() {
  const sessionId = useStore((s) => s.sessionId)
  const live = useStore((s) => s.live)
  const startLive = useStore((s) => s.startLive)
  const setLive = useStore((s) => s.setLive)
  const clearLive = useStore((s) => s.clearLive)
  const qc = useQueryClient()

  const { data: messages = [] } = useQuery({
    queryKey: ["messages", sessionId],
    queryFn: () => api.listMessages(sessionId!),
    enabled: !!sessionId,
  })

  if (!sessionId) {
    return <div className="flex flex-1 items-center justify-center text-slate-400">选择或新建一个会话开始聊天</div>
  }

  const onSend = async (text: string) => {
    startLive()
    let errored = false
    const { done } = streamTurn(sessionId, text, (e) => {
      if (e.type === "thinking_delta") setLive((t) => ({ ...t, thinking: t.thinking + e.text }))
      else if (e.type === "text_delta") setLive((t) => ({ ...t, text: t.text + e.text }))
      else if (e.type === "tool_call_start")
        setLive((t) => ({ ...t, toolCalls: [...t.toolCalls, { call: { id: e.call_id, name: e.tool, arguments: e.args } }] }))
      else if (e.type === "tool_result")
        setLive((t) => ({
          ...t,
          toolCalls: t.toolCalls.map((tc) =>
            tc.call.id === e.call_id ? { ...tc, result: { call_id: e.call_id, content: e.result, is_error: e.is_error } } : tc,
          ),
        }))
      else if (e.type === "turn_done") setLive((t) => ({ ...t, status: "done" }))
      else if (e.type === "error") { errored = true; setLive((t) => ({ ...t, status: "error", errorMessage: e.message })) }
    })
    try {
      await done
    } catch (err) {
      errored = true
      setLive((t) => ({ ...t, status: "error", errorMessage: String(err) }))
    }
    // 拉权威历史;成功则清掉 live(由落库消息替代),失败则保留错误态
    await qc.invalidateQueries({ queryKey: ["messages", sessionId] })
    if (!errored) clearLive()
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <MessageList messages={messages} />
      <Composer disabled={live?.status === "streaming"} onSend={onSend} />
    </div>
  )
}
```

- [ ] **Step 9: App 布局**

Replace `frontend/src/App.tsx` with:
```tsx
import { ChatView } from "./components/ChatView"
import { Sidebar } from "./components/Sidebar"

export default function App() {
  return (
    <div className="flex h-full">
      <Sidebar />
      <main className="flex min-w-0 flex-1 flex-col bg-slate-50">
        <ChatView />
      </main>
    </div>
  )
}
```

- [ ] **Step 10: 全量单测 + 构建**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && npx vitest run && npm run build
```
Expected: 全部测试通过(stream 3 + MessageBubble 3);构建成功。

- [ ] **Step 11: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add frontend/src && git commit -m "feat(frontend): streaming chat view (thinking/tools/text) + composer + app layout"
```

---

## Task 7: 设计细节打磨(浅色 + teal)

**Files:** Modify `frontend/src/index.css`(加流式光标/滚动条等细节);其余组件样式已在 Task 5–6 内置。

- [ ] **Step 1: 细节 CSS**

在 `frontend/src/index.css` 末尾追加(自定义滚动条 + 等宽数字 + 选中色):
```css
::selection { background: #99f6e4; }            /* brand-200 */
*::-webkit-scrollbar { width: 8px; height: 8px; }
*::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }  /* slate-300 */
*::-webkit-scrollbar-thumb:hover { background: #94a3b8; }                 /* slate-400 */
```

- [ ] **Step 2: 视觉自查(跑 dev,人工看)**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && npm run build
```
Expected: 构建通过。视觉走查放到 Task 8 起全栈后在浏览器做。

- [ ] **Step 3: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add frontend/src/index.css && git commit -m "style(frontend): scrollbar/selection polish (light+teal)"
```

---

## Task 8: 一键起全栈 dev 脚本 + 收尾

**Files:** Create `scripts/dev_up.sh`;(验证)前端构建/测试。

- [ ] **Step 1: dev_up.sh**

Create `scripts/dev_up.sh`:
```bash
#!/usr/bin/env bash
# 一键起全栈开发环境:Postgres(docker) + worker + backend(uvicorn) + frontend(vite)。
# 前置:仓库根 .env 里有 AGENT_CLOUD_WORKER_OPENAI_API_KEY / _BASE_URL;前端已 npm install。
# Ctrl-C 退出时清理后台进程。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PG_NAME="agent-cloud-pg"
PG_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/agent_cloud"

echo "[1/5] Postgres…"
if ! docker ps --format '{{.Names}}' | grep -q "^${PG_NAME}$"; then
  docker run -d --rm --name "$PG_NAME" -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=agent_cloud \
    -p 5432:5432 postgres:16 >/dev/null
fi
until docker exec "$PG_NAME" pg_isready -U postgres >/dev/null 2>&1; do sleep 0.5; done

echo "[2/5] migrate…"
( cd "$ROOT/services/backend" && AGENT_CLOUD_DATABASE_URL="$PG_URL" uv run alembic upgrade head )

pids=()
cleanup() { echo; echo "stopping…"; for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; docker stop "$PG_NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM

echo "[3/5] worker…"
( cd "$ROOT/services/worker" && uv run python -m agent_cloud_worker ) & pids+=($!)

echo "[4/5] backend (uvicorn :8000)…"
( cd "$ROOT/services/backend" && AGENT_CLOUD_DATABASE_URL="$PG_URL" AGENT_CLOUD_WORKER_ENDPOINT="localhost:50052" \
  AGENT_CLOUD_SANDBOX_BASE_ROOT="/tmp/agent-cloud-sandboxes" AGENT_CLOUD_OBJECT_STORE_ROOT="/tmp/agent-cloud-objstore" \
  uv run uvicorn agent_cloud_backend.main:app --port 8000 ) & pids+=($!)

echo "[5/5] frontend (vite :5173)…"
( cd "$ROOT/frontend" && npm run dev ) & pids+=($!)

echo "—— 打开 http://localhost:5173 —— (Ctrl-C 停止全部)"
wait
```

Make executable:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && chmod +x scripts/dev_up.sh
```

- [ ] **Step 2: 前端最终校验**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/frontend && npm run lint && npx vitest run && npm run build
```
Expected: lint 无错;全部单测通过;构建成功。

- [ ] **Step 3: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add scripts/dev_up.sh && git commit -m "chore: dev_up.sh — one-command full-stack dev (pg + worker + backend + frontend)"
```

---

## Self-Review(对照 spec)

- **范围=纯聊天闭环**:user/agent/session 选建(Task 5)+ 流式聊天(Task 6)+ 历史(ChatView 的 messages query)。✔ 文件/skills/配置编辑未做(spec 明确留后续)。✔
- **栈**:React+Vite+TS(T1)、TanStack Query(T4-6 的 useQuery/useMutation)、Zustand(T4 store)、Tailwind(T1 + 组件)、Vitest+RTL(T3 stream 测、T6 组件测)。✔
- **连接=Vite 代理**:vite.config proxy `/api`→:8000(T1);所有请求走 `/api`(client/stream)。✔ 后端零改动。✔
- **SSE=fetch 流式**:`parseSSE`+`streamTurn`(T3),ChatView 消费(T6)。✔
- **设计=浅色+teal**:tailwind `brand`=teal、index.css 浅底、组件 teal 主按钮/选中/光标(T1/5/6/7)。✔
- **dev_up.sh 一键起全栈**:T8。✔
- **测试**:SSE 解析器单测(T3)、关键组件渲染测(T6)。✔

类型一致性:`api.*`(client.ts)、`TurnEvent`/`Message`/`AgentConfig`/`Session`(types.ts)、`useStore` 的 `live/setLive/startLive/clearLive/setUser/setAgent/setSession`、`streamTurn`/`parseSSE`、组件 props —— 跨任务一致。✔

> 注:`scripts/dev_up.sh` 是人工运行的开发编排,不进单测;前端单测/构建覆盖代码正确性,全栈连通由 Task 8 起服务后在浏览器人工走查(发一条消息看流式 + 工具 + 落库)。
