import { afterEach, describe, expect, it, vi } from "vitest"
import { cancelTurn, parseSSE, resumeTurn, streamTurn } from "./stream"

afterEach(() => vi.unstubAllGlobals())

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

  it("skips a malformed data payload without throwing", () => {
    const events = collect([
      "data: not-json\n\n",
      'data: {"type":"text_delta","text":"ok"}\n\n',
    ])
    expect(events).toEqual([{ type: "text_delta", text: "ok" }])
  })
})

describe("resumeTurn", () => {
  it("returns null on 204 (no active turn)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })))
    expect(await resumeTurn("s1", () => {})).toBeNull()
  })
})

describe("streamTurn", () => {
  it("持续 409 → 自动重试 5 次后抛友好提示(而非原始 turn stream failed JSON)", async () => {
    vi.useFakeTimers()
    try {
      const f = vi.fn(async () => new Response('{"detail":"session is busy"}', { status: 409 }))
      vi.stubGlobal("fetch", f)
      const { done } = streamTurn("s1", "hi", () => {})
      const assertion = expect(done).rejects.toThrow("会话正忙(可能正在压缩上下文),请稍候重试")
      await vi.runAllTimersAsync() // 快进 4 轮 1.5s 重试间隔
      await assertion
      expect(f).toHaveBeenCalledTimes(5) // 首发 + 4 次重试
    } finally {
      vi.useRealTimers()
    }
  })

  it("409 一次后锁释放 → 自动重试成功,不抛错", async () => {
    vi.useFakeTimers()
    try {
      const sse = new Response(
        'data: {"type":"turn_done","usage":{"input_tokens":1,"output_tokens":1},"message_ids":[],"stop_reason":"end_turn"}\n\n',
        { status: 200 },
      )
      const f = vi
        .fn()
        .mockResolvedValueOnce(new Response('{"detail":"session is busy"}', { status: 409 }))
        .mockResolvedValueOnce(sse)
      vi.stubGlobal("fetch", f)
      const events: unknown[] = []
      const { done } = streamTurn("s1", "hi", (e) => events.push(e))
      await vi.runAllTimersAsync()
      await done // 不抛
      expect(f).toHaveBeenCalledTimes(2)
      expect(events.map((e) => (e as { type: string }).type)).toEqual(["turn_done"])
    } finally {
      vi.useRealTimers()
    }
  })

  it("其他非 2xx 仍带状态码(便于排查),不重试", async () => {
    const f = vi.fn(async () => new Response("boom", { status: 502 }))
    vi.stubGlobal("fetch", f)
    const { done } = streamTurn("s1", "hi", () => {})
    await expect(done).rejects.toThrow("turn stream failed: 502")
    expect(f).toHaveBeenCalledTimes(1)
  })
})

describe("cancelTurn", () => {
  it("POSTs the cancel endpoint", async () => {
    const f = vi.fn(async () => new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", f)
    await cancelTurn("s1")
    expect(f).toHaveBeenCalledWith(
      "/api/sessions/s1/turn/cancel",
      expect.objectContaining({ method: "POST" }),
    )
  })
})
