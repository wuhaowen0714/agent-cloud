import { describe, expect, it } from "vitest"
import {
  type Block,
  appendToSubagent,
  applyEvent,
  finishSubagent,
  startSubagent,
} from "./blocks"

const asSub = (b: Block) => b as Extract<Block, { kind: "subagent" }>

describe("subagent blocks", () => {
  it("startSubagent 新开块,幂等", () => {
    let b: Block[] = []
    b = startSubagent(b, "sub-1", "搜世界杯")
    expect(b).toHaveLength(1)
    expect(asSub(b[0])).toMatchObject({
      kind: "subagent", id: "sub-1", description: "搜世界杯", running: true, ok: true, blocks: [],
    })
    b = startSubagent(b, "sub-1", "搜世界杯") // 同 id 不重开
    expect(b).toHaveLength(1)
  })

  it("appendToSubagent 把事件应用到对应子块内部", () => {
    let b = startSubagent([], "sub-1", "x")
    b = appendToSubagent(b, "sub-1", { type: "text_delta", text: "hi" })
    b = appendToSubagent(b, "sub-1", {
      type: "tool_call_start", call_id: "c1", tool: "web_search", args: {},
    })
    const sub = asSub(b[0])
    expect(sub.blocks.map((x) => x.kind)).toEqual(["text", "tool"])
    expect(sub.blocks[1]).toMatchObject({ kind: "tool", id: "c1" })
  })

  it("appendToSubagent 找不到 id → 不改动该块", () => {
    const b = startSubagent([], "sub-1", "x")
    const b2 = appendToSubagent(b, "sub-9", { type: "text_delta", text: "hi" })
    expect(asSub(b2[0]).blocks).toHaveLength(0)
  })

  it("finishSubagent 标记 running=false + ok", () => {
    let b = startSubagent([], "sub-1", "x")
    b = finishSubagent(b, "sub-1", false)
    expect(asSub(b[0])).toMatchObject({ running: false, ok: false })
  })

  it("applyEvent 顶层组装 thinking/text/tool + 回填结果", () => {
    let b: Block[] = []
    b = applyEvent(b, { type: "thinking_delta", text: "想" })
    b = applyEvent(b, { type: "tool_call_start", call_id: "c1", tool: "bash", args: {} })
    b = applyEvent(b, { type: "tool_result", call_id: "c1", result: "ok", is_error: false })
    expect(b.map((x) => x.kind)).toEqual(["thinking", "tool"])
    const tool = b[1] as Extract<Block, { kind: "tool" }>
    expect(tool.result).toMatchObject({ content: "ok", is_error: false })
  })
})
