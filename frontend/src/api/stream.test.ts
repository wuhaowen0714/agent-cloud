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
  it("409 session busy → 抛友好提示(而非原始 turn stream failed JSON)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response('{"detail":"session is busy"}', { status: 409 })),
    )
    const { done } = streamTurn("s1", "hi", () => {})
    await expect(done).rejects.toThrow("会话正忙(可能正在压缩上下文),请稍候重试")
  })

  it("其他非 2xx 仍带状态码(便于排查)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 502 })))
    const { done } = streamTurn("s1", "hi", () => {})
    await expect(done).rejects.toThrow("turn stream failed: 502")
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
