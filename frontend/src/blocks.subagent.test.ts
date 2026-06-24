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

  it("applyEvent 忽略 task 工具调用(由 subagent 卡承载,防 live 顶层重复一张工具卡)", () => {
    const b = applyEvent([], {
      type: "tool_call_start",
      call_id: "c1",
      tool: "task",
      args: { description: "x", prompt: "y" },
    })
    expect(b).toHaveLength(0) // 顶层不建 task 工具块
  })

  it("C1 回归:完整 task 事件序 → 只一张 subagent 块,顶层无重复 task 工具卡", () => {
    // 复现 worker 的事件序:裸 task 事件不带 subagent_id(走 applyEvent),子事件带(进 subagent)
    let b: Block[] = []
    b = applyEvent(b, {
      type: "tool_call_start", call_id: "c1", tool: "task",
      args: { description: "搜", prompt: "p" },
    }) // 裸 task start → 拦截,不建顶层
    b = startSubagent(b, "sub-1", "搜") // subagent_started
    b = appendToSubagent(b, "sub-1", {
      type: "tool_call_start", call_id: "w1", tool: "web_search", args: {},
    }) // 子事件 → 进 subagent 内部
    b = finishSubagent(b, "sub-1", true) // subagent_done
    b = applyEvent(b, { type: "tool_result", call_id: "c1", result: "结果", is_error: false })
    // ↑ 裸 task result:attachToolResult 找不到顶层 c1 块,原样返回、无害
    expect(b).toHaveLength(1) // 顶层只一个块
    expect(b[0].kind).toBe("subagent")
    const sub = b[0] as Extract<Block, { kind: "subagent" }>
    expect(sub.blocks.map((x) => x.kind)).toEqual(["tool"]) // 内部一个 web_search
  })
})
