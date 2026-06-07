# Plan 10b: Reconnectable Turns — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After opening a session or refreshing the page, re-attach to an in-progress turn (replay + live) instead of losing it; switching away closes only the client connection (the server turn keeps running); add a **stop** button that cancels the server turn. Depends on Plan 10a (backend `GET /turn/stream` 204/replay + `POST /turn/cancel`).

**Architecture:** `api/stream.ts` gains `resumeTurn` (GET; `null` on 204) and `cancelTurn` (POST). `live` is tagged with its `sessionId`. `ChatView` runs a shared `consume()` for both the send-stream (POST) and the resume-stream (GET); a resume effect attaches on session-open when there's an active turn; the switch/unmount cleanup `abort()`s the **client** connection only (no cancel). `Composer` shows 停止 while streaming. Spec: [2026-06-08-reconnectable-turns-design.md](../specs/2026-06-08-reconnectable-turns-design.md).

**Tech Stack:** React 19, TanStack Query, Zustand, Vitest + RTL. `lint`=`tsc -b`; `test`=`vitest run`.

---

## File Structure

- Modify: `frontend/src/api/stream.ts` — `resumeTurn`, `cancelTurn`.
- Modify: `frontend/src/store.ts` — `LiveTurn.sessionId`; `startLive(userText, sessionId)`.
- Modify: `frontend/src/components/Composer.tsx` — `onStop` prop + 停止 button while streaming.
- Modify: `frontend/src/components/ChatView.tsx` — `feed`/`consume`, resume-on-open effect, abort-not-cancel on switch, `onStop`.
- Modify: `frontend/src/api/stream.test.ts` — `resumeTurn` 204 + `cancelTurn` tests.
- Create: `frontend/src/components/Composer.test.tsx` — stop button.

---

## Task 1: stream.ts (resume + cancel) + store tag

**Files:** Modify `api/stream.ts`, `store.ts`.

- [ ] **Step 1: Add `resumeTurn` + `cancelTurn`**

Append to `api/stream.ts`:

```typescript
/** GET 续看进行中回合:204 → null(没有在跑);否则补播+实时,返回可中断句柄。 */
export async function resumeTurn(
  sessionId: string,
  onEvent: (e: TurnEvent) => void,
): Promise<{ done: Promise<void>; abort: () => void } | null> {
  const ctrl = new AbortController()
  const res = await fetch(`/api/sessions/${sessionId}/turn/stream`, { signal: ctrl.signal })
  if (res.status === 204 || !res.body) return null
  if (!res.ok) throw new Error(`resume failed: ${res.status}`)
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  const feed = parseSSE(onEvent)
  const done = (async () => {
    for (;;) {
      const { done: rdone, value } = await reader.read()
      if (rdone) break
      feed(decoder.decode(value, { stream: true }))
    }
  })()
  return { done, abort: () => ctrl.abort() }
}

/** 主动停止服务端正在跑的回合(幂等)。 */
export async function cancelTurn(sessionId: string): Promise<void> {
  await fetch(`/api/sessions/${sessionId}/turn/cancel`, { method: "POST" })
}
```

(`parseSSE` and `TurnEvent` are already imported/defined in this file.)

- [ ] **Step 2: Tag `live` with its session**

In `store.ts`:
- Add `sessionId: string` to `LiveTurn`.
- `EMPTY`: add `sessionId: ""`.
- Change `startLive` signature + impl:

```typescript
  startLive: (userText: string, sessionId: string) => void
```
```typescript
  startLive: (userText, sessionId) => set({ live: { ...EMPTY, userText, sessionId, blocks: [] } }),
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npm run -s lint`
Expected: FAIL — `ChatView` calls `startLive(text)` with one arg now. (Fixed in Task 3.) Proceed; Task 3 fixes ChatView. To keep this task green on its own, temporarily it's fine — but prefer to do Task 3 before re-running lint. (If executing strictly per-task, run lint after Task 3.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/stream.ts frontend/src/store.ts
git commit -m "feat(frontend): resumeTurn/cancelTurn + tag live with sessionId"
```

---

## Task 2: Composer stop button

**Files:** Modify `components/Composer.tsx`; Create `components/Composer.test.tsx`.

- [ ] **Step 1: Add `onStop` + 停止 button**

Rewrite `Composer.tsx`:

```tsx
import { useState } from "react"

export function Composer({
  disabled, onSend, onStop,
}: {
  disabled: boolean
  onSend: (text: string) => void
  onStop?: () => void
}) {
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
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault()
            send()
          }
        }}
      />
      {disabled && onStop ? (
        <button
          className="rounded-lg border border-slate-300 px-4 text-sm text-slate-600 hover:bg-slate-50"
          onClick={onStop}
        >
          停止
        </button>
      ) : (
        <button
          className="rounded-lg bg-brand-600 px-4 text-sm text-white enabled:hover:bg-brand-700 disabled:opacity-40"
          disabled={disabled}
          onClick={send}
        >
          发送
        </button>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Test the stop button**

`components/Composer.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { Composer } from "./Composer"

describe("Composer", () => {
  it("shows 发送 when idle and calls onSend", () => {
    const onSend = vi.fn()
    render(<Composer disabled={false} onSend={onSend} onStop={() => {}} />)
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "hi" } })
    fireEvent.click(screen.getByText("发送"))
    expect(onSend).toHaveBeenCalledWith("hi")
  })

  it("shows 停止 while streaming and calls onStop", () => {
    const onStop = vi.fn()
    render(<Composer disabled onSend={() => {}} onStop={onStop} />)
    expect(screen.queryByText("发送")).not.toBeInTheDocument()
    fireEvent.click(screen.getByText("停止"))
    expect(onStop).toHaveBeenCalled()
  })
})
```

- [ ] **Step 3: Run test + commit**

Run: `cd frontend && npx vitest run src/components/Composer.test.tsx` → PASS.

```bash
git add frontend/src/components/Composer.tsx frontend/src/components/Composer.test.tsx
git commit -m "feat(frontend): Composer stop button (cancel running turn)"
```

---

## Task 3: ChatView — resume on open, abort-not-cancel on switch, stop wiring

**Files:** Modify `components/ChatView.tsx`.

- [ ] **Step 1: Rewrite `ChatView.tsx`**

```tsx
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef } from "react"
import { api } from "../api/client"
import { cancelTurn, resumeTurn, streamTurn } from "../api/stream"
import { appendDelta, appendToolCall, attachToolResult } from "../blocks"
import { useStore } from "../store"
import type { TurnEvent } from "../types"
import { Composer } from "./Composer"
import { MessageList } from "./MessageList"

export function ChatView() {
  const sessionId = useStore((s) => s.sessionId)
  const live = useStore((s) => s.live)
  const startLive = useStore((s) => s.startLive)
  const setLive = useStore((s) => s.setLive)
  const clearLive = useStore((s) => s.clearLive)
  const qc = useQueryClient()
  // 在途客户端连接(POST 或 GET resume)的中断句柄 + 所属会话
  const inflight = useRef<{ abort: () => void; sessionId: string } | null>(null)

  const { data: messages = [] } = useQuery({
    queryKey: ["messages", sessionId],
    queryFn: () => api.listMessages(sessionId!),
    enabled: !!sessionId,
  })

  // 把一个回合事件灌进 live(仅当仍停留在该会话,丢弃切走会话的残余事件)
  const feed = (sid: string, e: TurnEvent) => {
    if (useStore.getState().sessionId !== sid) return
    if (e.type === "thinking_delta")
      setLive((t) => ({ ...t, blocks: appendDelta(t.blocks, "thinking", e.text) }))
    else if (e.type === "text_delta")
      setLive((t) => ({ ...t, blocks: appendDelta(t.blocks, "text", e.text) }))
    else if (e.type === "tool_call_start")
      setLive((t) => ({ ...t, blocks: appendToolCall(t.blocks, { id: e.call_id, name: e.tool, arguments: e.args }) }))
    else if (e.type === "tool_result")
      setLive((t) => ({ ...t, blocks: attachToolResult(t.blocks, e.call_id, { call_id: e.call_id, content: e.result, is_error: e.is_error }) }))
    else if (e.type === "turn_done") setLive((t) => ({ ...t, status: "done" }))
    else if (e.type === "error") setLive((t) => ({ ...t, status: "error", errorMessage: e.message }))
  }

  // 消费一个流(POST 或 GET resume)到结束:成功→刷新历史+清 live;主动中断(切走)→不动。
  const consume = async (sid: string, handle: { done: Promise<void>; abort: () => void }) => {
    inflight.current = { abort: handle.abort, sessionId: sid }
    try {
      await handle.done
    } catch (err) {
      const aborted = err instanceof DOMException && err.name === "AbortError"
      if (aborted) return // 切走/卸载导致的中断:服务端回合仍在跑,切回再 resume,这里不收尾
      if (useStore.getState().sessionId === sid)
        setLive((t) => ({ ...t, status: "error", errorMessage: String(err) }))
    }
    if (inflight.current?.sessionId === sid) inflight.current = null
    const errored = useStore.getState().live?.status === "error"
    await qc.invalidateQueries({ queryKey: ["messages", sid] })
    if (!errored && useStore.getState().sessionId === sid) clearLive()
  }

  // 切会话/卸载:中断【客户端连接】(服务端回合继续);不再 cancel。
  useEffect(() => {
    return () => {
      inflight.current?.abort()
      inflight.current = null
    }
  }, [sessionId])

  // 打开会话/刷新后:若该会话有进行中回合、且当前没有本会话的 live,挂上去续看(补播+实时)。
  useEffect(() => {
    const sid = sessionId
    if (!sid) return
    if (useStore.getState().live?.sessionId === sid) return // 刚 POST 起的,别重复挂
    let cancelledLocal = false
    let abortFn: (() => void) | null = null
    void (async () => {
      const handle = await resumeTurn(sid, (e) => feed(sid, e))
      if (!handle) return // 204:没有在跑的回合
      if (cancelledLocal || useStore.getState().sessionId !== sid) {
        handle.abort()
        return
      }
      abortFn = handle.abort
      startLive("", sid) // user 消息由已落库 messages 渲染;live 只放助手 blocks
      await consume(sid, handle)
    })()
    return () => {
      cancelledLocal = true
      abortFn?.()
    }
  }, [sessionId])

  if (!sessionId) {
    return (
      <div className="flex flex-1 items-center justify-center text-slate-400">
        选择或新建一个会话开始聊天
      </div>
    )
  }

  const onSend = async (text: string) => {
    if (useStore.getState().live?.status === "streaming") return
    const sid = sessionId
    startLive(text, sid)
    await consume(sid, streamTurn(sid, text, (e) => feed(sid, e)))
  }

  const onStop = () => {
    if (sessionId) void cancelTurn(sessionId)
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <MessageList messages={messages} />
      <Composer disabled={live?.status === "streaming"} onSend={onSend} onStop={onStop} />
    </div>
  )
}
```

Notes on behavior:
- **Send**: `startLive(text, sid)` (optimistic user bubble) → POST stream → `consume`.
- **Switch away**: the `[sessionId]` cleanup `abort()`s the client connection; the server turn keeps running. `consume` sees `AbortError` → returns without clearing. Switch back → resume effect re-attaches (GET replay + live).
- **Refresh**: on mount the resume effect GETs; active turn → replay+live; none → 204 → nothing.
- **Stop**: `cancelTurn` → server cancels → runner emits `error: turn cancelled` → live shows error.
- The resume effect skips when `live.sessionId === sid` (we just sent) to avoid double-attaching.

- [ ] **Step 2: Type-check + full frontend regression**

Run: `cd frontend && npm run -s lint && npm run -s test`
Expected: `tsc -b` exit 0; all suites pass (existing + Composer + stream tests).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ChatView.tsx
git commit -m "feat(frontend): resume in-progress turn on session open/refresh; stop button"
```

---

## Task 4: stream.ts tests + live verification

**Files:** Modify `api/stream.test.ts`.

- [ ] **Step 1: Add resume/cancel unit tests**

Append to `api/stream.test.ts`:

```typescript
import { cancelTurn, resumeTurn } from "./stream"
import { afterEach, vi } from "vitest"

afterEach(() => vi.unstubAllGlobals())

describe("resumeTurn", () => {
  it("returns null on 204 (no active turn)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })))
    expect(await resumeTurn("s1", () => {})).toBeNull()
  })
})

describe("cancelTurn", () => {
  it("POSTs the cancel endpoint", async () => {
    const f = vi.fn(async () => new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", f)
    await cancelTurn("s1")
    expect(f).toHaveBeenCalledWith("/api/sessions/s1/turn/cancel", { method: "POST" })
  })
})
```

(If `describe`/`it` aren't auto-global, add them to the existing import from `vitest` at the top of the file.)

- [ ] **Step 2: Run frontend tests**

Run: `cd frontend && npm run -s test`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/stream.test.ts
git commit -m "test(frontend): resumeTurn 204 + cancelTurn"
```

- [ ] **Step 4: Live verification (preview tools, after a stack restart so the backend has the new endpoints)**

With the full stack restarted (`bash scripts/dev_up.sh`): open a session, send a multi-step message, then mid-stream (a) switch to another session and back → the turn should still be streaming/continue and complete; (b) refresh the page → the turn should re-attach (replay + live) and finish; (c) click 停止 mid-turn → it stops and shows cancelled. Verify with `preview_console_logs` (clean) + `preview_screenshot`.

---

## Self-Review

- **Spec coverage:** resume on open/refresh (GET, replay+live) ✓; switch = abort client only, server continues ✓; refresh re-attaches ✓; stop button → cancel ✓; live tagged by session to avoid double-attach ✓; user msg from history (no dup) ✓.
- **Consistency:** `startLive(userText, sessionId)` updated at both call sites (onSend, resume); `consume` shared by POST & GET; `feed` guards on current session; `inflight.abort` = client disconnect (not cancel).
- **Edge cases:** AbortError on switch → no clear/refetch (server turn lives); error event → keep live in error; 204 resume → no live.
- **No placeholders:** full code + commands per step.
- **Verification:** unit tests for the new pieces; the full ChatView reconnect flow validated via live preview (Task 4 step 4) since SSE+navigation is impractical to unit-test.
