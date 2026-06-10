# 消息时间戳 + 代码块对比度修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提问/回答气泡下显示消息时间;修复深色代码块文字对比度 bug。

**Architecture:** 纯前端。后端 `MessageRead` 已返回 `created_at`(timestamptz → ISO 带偏移),前端补类型、`messagesToTurns` 带出 `userAt`/`doneAt`、`fmtTime` 三档格式化、MessageList 渲染;live 用户气泡时间记在 `store.startLive` 的 `startedAt`。代码块 bug 是 `prose-code:text-brand-700` 零特异性泄漏进 `pre code`,一个 `[&_pre_code]:text-inherit` 任意变体类压回。

**Tech Stack:** React19 + zustand + vitest + @tailwindcss/typography。

参考 spec:`docs/superpowers/specs/2026-06-10-chat-timestamps-code-contrast-design.md`(c090807)

---

## Task 1: fmtTime 三档格式化

**Files:**
- Create: `frontend/src/time.ts`
- Test: `frontend/src/time.test.ts`

- [ ] **Step 1: 失败测试**(新文件 time.test.ts)

```ts
import { describe, expect, it } from "vitest"
import { fmtTime } from "./time"

// 无时区后缀的 ISO 按本地时区解析,与 fmtTime 的本地输出一致 → 断言跨机器稳定
describe("fmtTime", () => {
  const now = new Date("2026-06-10T20:00:00")

  it("今天:只显示时分(补零)", () => {
    expect(fmtTime("2026-06-10T14:32:00", now)).toBe("14:32")
    expect(fmtTime("2026-06-10T09:05:00", now)).toBe("09:05")
  })

  it("今年非今天:月-日 时:分", () => {
    expect(fmtTime("2026-03-05T09:07:00", now)).toBe("03-05 09:07")
  })

  it("跨年:全量日期", () => {
    expect(fmtTime("2025-12-31T23:59:00", now)).toBe("2025-12-31 23:59")
  })
})
```

- [ ] **Step 2: 确认失败** — Run: `cd frontend && npx vitest run src/time.test.ts`,Expected: 找不到模块 `./time`

- [ ] **Step 3: 实现**(新文件 time.ts)

```ts
// 消息时间戳:与「现在」同日只给时分;同年给 月-日 时:分;跨年给全量。本地时区,24h 制。
// now 可注入仅为测试确定性;生产调用走默认值。
export function fmtTime(iso: string, now: Date = new Date()): string {
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, "0")
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  if (sameDay) return hm
  const md = `${p(d.getMonth() + 1)}-${p(d.getDate())}`
  if (d.getFullYear() === now.getFullYear()) return `${md} ${hm}`
  return `${d.getFullYear()}-${md} ${hm}`
}
```

- [ ] **Step 4: 测试过** — Run: `cd frontend && npx vitest run src/time.test.ts`,Expected: 3 PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/time.ts frontend/src/time.test.ts
git commit -m "feat(frontend): fmtTime — 今天/今年/跨年三档消息时间格式"
```

## Task 2: Message.created_at + Turn.userAt/doneAt

**Files:**
- Modify: `frontend/src/types.ts:15`(Message 加 created_at)
- Modify: `frontend/src/blocks.ts`(Turn 接口 + messagesToTurns)
- Test: `frontend/src/blocks.test.ts`(mk() 基座补 created_at + 新断言)

- [ ] **Step 1: 失败测试**(blocks.test.ts:`mk` 基座加 `created_at: "2026-06-10T10:00:00"`;文件末尾追加)

```ts
describe("messagesToTurns 时间戳", () => {
  it("userAt 取 user 消息时间,doneAt 取回合最后一条消息时间", () => {
    const messages: Message[] = [
      mk({ id: "u1", seq: 0, role: "user", content: { text: "q", tool_calls: [], tool_results: [] }, created_at: "2026-06-10T10:00:00" }),
      mk({ id: "a1", seq: 1, role: "assistant", content: { text: "checking", tool_calls: [{ id: "c1", name: "bash", arguments: {} }], tool_results: [] }, created_at: "2026-06-10T10:01:00" }),
      mk({ id: "t1", seq: 2, role: "tool", content: { text: "", tool_calls: [], tool_results: [{ call_id: "c1", content: "ok", is_error: false }] }, created_at: "2026-06-10T10:02:00" }),
      mk({ id: "a2", seq: 3, role: "assistant", content: { text: "done", tool_calls: [], tool_results: [] }, created_at: "2026-06-10T10:03:00" }),
    ]
    const turns = messagesToTurns(messages)
    expect(turns[0].userAt).toBe("2026-06-10T10:00:00")
    expect(turns[0].doneAt).toBe("2026-06-10T10:03:00")
  })

  it("无 user 消息的孤儿回合:userAt 为 null,doneAt 仍取最后一条", () => {
    const turns = messagesToTurns([
      mk({ id: "a1", seq: 0, role: "assistant", content: { text: "hi", tool_calls: [], tool_results: [] }, created_at: "2026-06-10T11:00:00" }),
    ])
    expect(turns[0].userAt).toBeNull()
    expect(turns[0].doneAt).toBe("2026-06-10T11:00:00")
  })

  it("只有 user 消息(未完成回合):doneAt 为 null", () => {
    const turns = messagesToTurns([
      mk({ id: "u1", seq: 0, role: "user", content: { text: "q", tool_calls: [], tool_results: [] }, created_at: "2026-06-10T12:00:00" }),
    ])
    expect(turns[0].userAt).toBe("2026-06-10T12:00:00")
    expect(turns[0].doneAt).toBeNull()
  })
})
```

- [ ] **Step 2: 确认失败** — Run: `cd frontend && npx vitest run src/blocks.test.ts`,Expected: TS/断言失败(Turn 无 userAt)

- [ ] **Step 3: 实现**

`types.ts` Message 行改为:

```ts
export interface Message { id: string; seq: number; role: "user" | "assistant" | "tool"; content: MessageContent; created_at: string }
```

`blocks.ts` Turn 接口与 messagesToTurns 改为:

```ts
// 历史里一个回合:可能有用户消息(userText),以及该回合的展示块。
export interface Turn {
  id: string
  userText: string | null
  userAt: string | null // user 消息时间(提问气泡下显示)
  doneAt: string | null // 回合最后一条 assistant/tool 消息时间 = 回答完成时间
  blocks: Block[]
}
```

```ts
export function messagesToTurns(messages: Message[]): Turn[] {
  const turns: Turn[] = []
  let cur: {
    id: string; user: string | null; userAt: string | null; lastAt: string | null
    assistants: Message[]; results: Map<string, ToolResult>
  } | null = null

  const flush = () => {
    if (!cur) return
    const blocks: Block[] = []
    for (const m of cur.assistants) {
      if (m.content.text) blocks.push({ kind: "text", id: `${m.id}-text`, text: m.content.text })
      for (const c of m.content.tool_calls) {
        blocks.push({ kind: "tool", id: c.id, call: c, result: cur.results.get(c.id) })
      }
    }
    turns.push({ id: cur.id, userText: cur.user, userAt: cur.userAt, doneAt: cur.lastAt, blocks })
    cur = null
  }

  for (const m of messages) {
    if (m.role === "user") {
      flush()
      cur = { id: m.id, user: m.content.text, userAt: m.created_at, lastAt: null, assistants: [], results: new Map() }
    } else {
      if (!cur) cur = { id: m.id, user: null, userAt: null, lastAt: null, assistants: [], results: new Map() }
      cur.lastAt = m.created_at // 回合内任何 assistant/tool 消息都推进“完成时间”
      if (m.role === "tool") {
        for (const r of m.content.tool_results) cur.results.set(r.call_id, r)
      } else {
        cur.assistants.push(m)
      }
    }
  }
  flush()
  return turns
}
```

- [ ] **Step 4: 测试过 + 全套** — Run: `cd frontend && npx vitest run && npm run lint`,Expected: 全 PASS(若其它测试有构造 Message 字面量处,补 `created_at` 字段)

- [ ] **Step 5: 提交**

```bash
git add frontend/src/types.ts frontend/src/blocks.ts frontend/src/blocks.test.ts
git commit -m "feat(frontend): turns carry userAt/doneAt timestamps"
```

## Task 3: store.startedAt + MessageList 渲染

**Files:**
- Modify: `frontend/src/store.ts`(LiveTurn + EMPTY + startLive)
- Modify: `frontend/src/components/MessageList.tsx`
- Test: `frontend/src/components/MessageList.test.tsx`

- [ ] **Step 1: 失败测试**(MessageList.test.tsx:`setErrorLive` 的 live 对象补 `startedAt: "2026-06-10T09:00:00"`;顶部加 `import type { Message } from "../types"`;末尾追加)

```tsx
const msg = (over: Partial<Message>): Message => ({
  id: "m", seq: 0, role: "user",
  content: { text: "你好", tool_calls: [], tool_results: [] },
  created_at: "2026-06-10T14:32:00", ...over,
})

describe("MessageList 时间戳", () => {
  it("历史回合:提问与回答下方显示时间(断言时分,格式档位与运行日期无关)", () => {
    const messages: Message[] = [
      msg({ id: "u1", seq: 0 }),
      msg({
        id: "a1", seq: 1, role: "assistant",
        content: { text: "答案", tool_calls: [], tool_results: [] },
        created_at: "2026-06-10T14:35:00",
      }),
    ]
    render(<MessageList messages={messages} />)
    expect(screen.getByText(/14:32/)).toBeInTheDocument()
    expect(screen.getByText(/14:35/)).toBeInTheDocument()
  })

  it("live 流式:用户气泡下显示发送时间,助手侧无时间", () => {
    useStore.setState({
      live: { userText: "问", sessionId: "s1", blocks: [], status: "streaming", startedAt: "2026-06-10T09:05:00" },
    })
    render(<MessageList messages={[]} />)
    expect(screen.getByText(/09:05/)).toBeInTheDocument()
    expect(screen.getAllByText(/\d{2}:\d{2}/)).toHaveLength(1)
  })
})
```

- [ ] **Step 2: 确认失败** — Run: `cd frontend && npx vitest run src/components/MessageList.test.tsx`,Expected: TS 报错(LiveTurn 无 startedAt)/找不到时间文本

- [ ] **Step 3: 实现**

`store.ts`:

```ts
export interface LiveTurn {
  userText: string
  sessionId: string
  startedAt: string // 发送时刻(ISO);用户气泡下的时间(历史接管前的乐观显示)
  blocks: Block[]
  status: "streaming" | "done" | "error"
  errorMessage?: string
  recoverable?: boolean // 失败时是否可重试(false=如上下文过大,引导开新会话)
}
```

```ts
const EMPTY: LiveTurn = { userText: "", sessionId: "", startedAt: "", blocks: [], status: "streaming" }
```

```ts
  startLive: (userText, sessionId) =>
    set({ live: { ...EMPTY, userText, sessionId, blocks: [], startedAt: new Date().toISOString() } }),
```

`MessageList.tsx`:顶部加 `import { fmtTime } from "../time"`;历史回合渲染改为(气泡 + 时间行包成组,父级 `space-y-4` 作用于组):

```tsx
          <Fragment key={turn.id}>
            {turn.userText !== null && (
              <div className="space-y-1">
                <UserBubble text={turn.userText} />
                {turn.userAt && (
                  <div className="flex justify-end pr-1 text-[11px] text-slate-400">{fmtTime(turn.userAt)}</div>
                )}
              </div>
            )}
            {turn.blocks.length > 0 && (
              <div className="space-y-1">
                <AssistantBubble>
                  <TurnBlocks blocks={turn.blocks} />
                </AssistantBubble>
                {turn.doneAt && (
                  <div className="pl-1 text-[11px] text-slate-400">{fmtTime(turn.doneAt)}</div>
                )}
              </div>
            )}
            {unfinished && (
              <div className="text-center text-xs text-slate-400">— 回合未完成 —</div>
            )}
          </Fragment>
```

live 用户气泡改为(助手流式中不显示时间,turn_done 后历史接管自然补上):

```tsx
          {live.userText && (
            <div className="space-y-1">
              <UserBubble text={live.userText} />
              {live.startedAt && (
                <div className="flex justify-end pr-1 text-[11px] text-slate-400">{fmtTime(live.startedAt)}</div>
              )}
            </div>
          )}
```

- [ ] **Step 4: 测试过 + 全套** — Run: `cd frontend && npx vitest run && npm run lint`,Expected: 全 PASS(若其它测试构造 live 对象,补 `startedAt`)

- [ ] **Step 5: 提交**

```bash
git add frontend/src/store.ts frontend/src/components/MessageList.tsx frontend/src/components/MessageList.test.tsx
git commit -m "feat(frontend): timestamps under question/answer bubbles"
```

## Task 4: 代码块对比度修复

**Files:**
- Modify: `frontend/src/components/Markdown.tsx`
- Test: Create `frontend/src/components/Markdown.test.tsx`

- [ ] **Step 1: 失败测试**(新文件)

```tsx
import { render } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { Markdown } from "./Markdown"

describe("Markdown 代码块对比度", () => {
  it("包装类含 [&_pre_code]:text-inherit(防行内 code 颜色泄漏进深色代码块)", () => {
    const { container } = render(<Markdown>{"```\nconst x = 1\n```"}</Markdown>)
    const wrapper = container.firstElementChild as HTMLElement
    expect(wrapper.className).toContain("[&_pre_code]:text-inherit")
    expect(container.querySelector("pre code")).not.toBeNull()
  })
})
```

- [ ] **Step 2: 确认失败** — Run: `cd frontend && npx vitest run src/components/Markdown.test.tsx`,Expected: className 断言失败

- [ ] **Step 3: 实现** — `Markdown.tsx` 的 className 追加修复类(并补注释):

```tsx
// prose-code:text-brand-700 的 :where() 选择器命中 prose 内所有 code(含 pre>code),
// utility 后加载胜出 → 深 teal 落在 prose-pre 深底上看不清。[&_pre_code]:text-inherit
// 以真实后代选择器特异性压回:代码块继承 pre 的 text-slate-100,行内 code 的 teal 不变。
<div className="prose prose-sm prose-slate max-w-none prose-pre:bg-slate-800 prose-pre:text-slate-100 prose-code:text-brand-700 prose-code:before:content-none prose-code:after:content-none [&_pre_code]:text-inherit">
```

- [ ] **Step 4: 测试过 + 全套** — Run: `cd frontend && npx vitest run && npm run lint`,Expected: 全 PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/Markdown.tsx frontend/src/components/Markdown.test.tsx
git commit -m "fix(frontend): code blocks inherit pre color — inline-code teal leaked into dark pre"
```

## Task 5: 回归 + 对抗审查 + PR

- [ ] **回归**:`cd frontend && npx vitest run && npm run lint` 全绿(backend/worker/common 零改动,CI 兜底)。
- [ ] **Fable 5 对抗审查**(Agent tool,`model: "fable"`,diff 内联)重点:fmtTime 时区/解析边界(带偏移 ISO、Invalid Date)、messagesToTurns 既有语义回归、live startedAt 的构造点遗漏、`[&_pre_code]` 特异性论证、时间行与 space-y-4 的间距嵌套。修复后重跑。
- [ ] **PR**:推分支 → `gh pr create`(标题 `feat: message timestamps + code-block contrast fix`)→ CI 绿 → 等合并指令。
