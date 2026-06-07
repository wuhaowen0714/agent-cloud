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

  it("skips a malformed data payload without throwing", () => {
    const events = collect([
      "data: not-json\n\n",
      'data: {"type":"text_delta","text":"ok"}\n\n',
    ])
    expect(events).toEqual([{ type: "text_delta", text: "ok" }])
  })
})
