import { describe, expect, it } from "vitest"
import { appendDelta, appendToolCall, attachToolResult, dropPendingTools, messagesToTurns, upsertToolProgress, type Block } from "./blocks"
import type { Message } from "./types"

describe("appendDelta", () => {
  it("merges consecutive same-kind deltas into one block", () => {
    let b: Block[] = []
    b = appendDelta(b, "thinking", "he")
    b = appendDelta(b, "thinking", "llo")
    expect(b).toHaveLength(1)
    expect(b[0]).toMatchObject({ kind: "thinking", text: "hello" })
  })

  it("opens a new block when the kind switches (preserves order)", () => {
    let b: Block[] = []
    b = appendDelta(b, "thinking", "plan")
    b = appendDelta(b, "text", "answer")
    b = appendDelta(b, "thinking", "more")
    expect(b.map((x) => x.kind)).toEqual(["thinking", "text", "thinking"])
    expect(b.map((x) => (x as { text: string }).text)).toEqual(["plan", "answer", "more"])
  })

  it("does not mutate the input array", () => {
    const a: Block[] = []
    const out = appendDelta(a, "text", "x")
    expect(a).toHaveLength(0)
    expect(out).toHaveLength(1)
  })
})

describe("appendToolCall / attachToolResult", () => {
  it("appends a tool block then fills its result by call_id, keeping position", () => {
    let b: Block[] = []
    b = appendDelta(b, "thinking", "let me look")
    b = appendToolCall(b, { id: "c1", name: "bash", arguments: { command: "ls" } })
    b = appendDelta(b, "text", "done")
    // result arrives after later blocks already exist — must land on the original tool block
    b = attachToolResult(b, "c1", { call_id: "c1", content: "a.txt", is_error: false })
    expect(b.map((x) => x.kind)).toEqual(["thinking", "tool", "text"])
    const tool = b[1] as Extract<Block, { kind: "tool" }>
    expect(tool.call.name).toBe("bash")
    expect(tool.result?.content).toBe("a.txt")
  })

  it("ignores a result whose call_id matches nothing", () => {
    let b = appendToolCall([], { id: "c1", name: "bash", arguments: {} })
    b = attachToolResult(b, "nope", { call_id: "nope", content: "x", is_error: false })
    expect((b[0] as Extract<Block, { kind: "tool" }>).result).toBeUndefined()
  })
})

const mk = (over: Partial<Message>): Message => ({
  id: "m", seq: 0, role: "assistant",
  content: { text: "", tool_calls: [], tool_results: [] }, ...over,
})

describe("messagesToTurns", () => {
  it("groups a multi-step turn into one chronological block list, pairing results", () => {
    const messages: Message[] = [
      mk({ id: "u1", seq: 0, role: "user", content: { text: "run it", tool_calls: [], tool_results: [] } }),
      mk({ id: "a1", seq: 1, role: "assistant", content: { text: "checking", tool_calls: [{ id: "c1", name: "bash", arguments: { command: "ls" } }], tool_results: [] } }),
      mk({ id: "t1", seq: 2, role: "tool", content: { text: "", tool_calls: [], tool_results: [{ call_id: "c1", content: "a.txt", is_error: false }] } }),
      mk({ id: "a2", seq: 3, role: "assistant", content: { text: "all done", tool_calls: [], tool_results: [] } }),
    ]
    const turns = messagesToTurns(messages)
    expect(turns).toHaveLength(1)
    expect(turns[0].id).toBe("u1")
    expect(turns[0].userText).toBe("run it")
    // text("checking") → tool(c1 → a.txt) → text("all done"), in time order
    expect(turns[0].blocks.map((b) => b.kind)).toEqual(["text", "tool", "text"])
    const tool = turns[0].blocks[1] as Extract<Block, { kind: "tool" }>
    expect(tool.result?.content).toBe("a.txt")
  })

  it("splits separate user questions into separate turns", () => {
    const messages: Message[] = [
      mk({ id: "u1", seq: 0, role: "user", content: { text: "q1", tool_calls: [], tool_results: [] } }),
      mk({ id: "a1", seq: 1, role: "assistant", content: { text: "a1", tool_calls: [], tool_results: [] } }),
      mk({ id: "u2", seq: 2, role: "user", content: { text: "q2", tool_calls: [], tool_results: [] } }),
      mk({ id: "a2", seq: 3, role: "assistant", content: { text: "a2", tool_calls: [], tool_results: [] } }),
    ]
    const turns = messagesToTurns(messages)
    expect(turns.map((t) => t.userText)).toEqual(["q1", "q2"])
    expect(turns.map((t) => t.blocks.length)).toEqual([1, 1])
  })

  it("returns no turns for empty input", () => {
    expect(messagesToTurns([])).toEqual([])
  })
})

describe("upsertToolProgress / pending 升级", () => {
  const prog = (chars: number) => ({
    call_id: "c1", tool: "write_file", args_chars: chars, lines: 3, path: "a.py",
  })

  it("首个进度新开 pending 卡,后续原位更新计数", () => {
    let b: Block[] = []
    b = upsertToolProgress(b, prog(10))
    b = upsertToolProgress(b, prog(99))
    expect(b).toHaveLength(1)
    const t = b[0] as Extract<Block, { kind: "tool" }>
    expect(t.progress).toMatchObject({ argsChars: 99, lines: 3, path: "a.py" })
    expect(t.call.name).toBe("write_file")
  })

  it("tool_call_start 原位替换 pending 卡(位置与 id 不变,progress 清掉)", () => {
    let b: Block[] = []
    b = appendDelta(b, "text", "before")
    b = upsertToolProgress(b, prog(10))
    b = appendToolCall(b, { id: "c1", name: "write_file", arguments: { path: "a.py", content: "x" } })
    expect(b.map((x) => x.kind)).toEqual(["text", "tool"])
    const t = b[1] as Extract<Block, { kind: "tool" }>
    expect(t.progress).toBeUndefined()
    expect(t.call.arguments).toMatchObject({ path: "a.py" })
  })

  it("真卡之后迟到的进度被忽略(原引用返回)", () => {
    let b: Block[] = []
    b = appendToolCall(b, { id: "c1", name: "bash", arguments: { command: "ls" } })
    const out = upsertToolProgress(b, { call_id: "c1", tool: "bash", args_chars: 5, lines: 1, path: "" })
    expect(out).toBe(b)
  })

  it("appendToolCall 无 pending 时仍尾部追加(回归)", () => {
    let b: Block[] = []
    b = appendDelta(b, "text", "t")
    b = appendToolCall(b, { id: "c9", name: "bash", arguments: {} })
    expect(b.map((x) => x.kind)).toEqual(["text", "tool"])
  })
})

describe("dropPendingTools(error/cancel 终态)", () => {
  it("只剥 pending 进度卡,保留真卡与半截文本", () => {
    let b: Block[] = []
    b = appendDelta(b, "text", "half answer")
    b = appendToolCall(b, { id: "c0", name: "bash", arguments: { command: "ls" } })
    b = upsertToolProgress(b, { call_id: "c1", tool: "write_file", args_chars: 9, lines: 1, path: "" })
    const out = dropPendingTools(b)
    expect(out.map((x) => x.kind)).toEqual(["text", "tool"])
    expect((out[1] as Extract<Block, { kind: "tool" }>).id).toBe("c0")
  })
})
