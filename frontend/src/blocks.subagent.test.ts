import { describe, expect, it } from "vitest"
import {
  type Block,
  appendToSubagent,
  applyEvent,
  finishSubagent,
  messagesToTurns,
  startSubagent,
} from "./blocks"
import type { Message } from "./types"

const asSub = (b: Block) => b as Extract<Block, { kind: "subagent" }>

describe("subagent blocks", () => {
  it("startSubagent 新开块(带 prompt),幂等", () => {
    let b: Block[] = []
    b = startSubagent(b, "sub-1", "搜世界杯", "搜今天的比分")
    expect(b).toHaveLength(1)
    expect(asSub(b[0])).toMatchObject({
      kind: "subagent", id: "sub-1", description: "搜世界杯", prompt: "搜今天的比分",
      running: true, ok: true, blocks: [],
    })
    b = startSubagent(b, "sub-1", "搜世界杯", "搜今天的比分") // 同 id 不重开
    expect(b).toHaveLength(1)
  })

  it("appendToSubagent 把事件应用到对应子块内部", () => {
    let b = startSubagent([], "sub-1", "x", "")
    b = appendToSubagent(b, "sub-1", { type: "text_delta", text: "hi" })
    b = appendToSubagent(b, "sub-1", {
      type: "tool_call_start", call_id: "c1", tool: "web_search", args: {},
    })
    const sub = asSub(b[0])
    expect(sub.blocks.map((x) => x.kind)).toEqual(["text", "tool"])
    expect(sub.blocks[1]).toMatchObject({ kind: "tool", id: "c1" })
  })

  it("appendToSubagent 找不到 id → 不改动该块", () => {
    const b = startSubagent([], "sub-1", "x", "")
    const b2 = appendToSubagent(b, "sub-9", { type: "text_delta", text: "hi" })
    expect(asSub(b2[0]).blocks).toHaveLength(0)
  })

  it("finishSubagent 标记 running=false + ok", () => {
    let b = startSubagent([], "sub-1", "x", "")
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
    b = startSubagent(b, "sub-1", "搜", "") // subagent_started
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

  it("messagesToTurns:子消息(parent_call_id)重建进对应 task 的 subagent 卡 + prompt(A+B)", () => {
    const messages: Message[] = [
      { id: "u", seq: 0, role: "user", created_at: "t",
        content: { text: "查世界杯", tool_calls: [], tool_results: [] } },
      { id: "a1", seq: 1, role: "assistant", created_at: "t", content: {
        text: "", tool_results: [],
        tool_calls: [{ id: "task1", name: "task", arguments: { description: "查战况", prompt: "查今天比分" } }],
      } },
      // 子 agent 过程(parent_call_id=task1):web_search + 结果 + 收尾
      { id: "s1", seq: 2, role: "assistant", created_at: "t", content: {
        text: "", tool_results: [], parent_call_id: "task1",
        tool_calls: [{ id: "w1", name: "web_search", arguments: { query: "世界杯" } }],
      } },
      { id: "s2", seq: 3, role: "tool", created_at: "t", content: {
        text: "", tool_calls: [], parent_call_id: "task1",
        tool_results: [{ call_id: "w1", content: "搜索结果", is_error: false }],
      } },
      { id: "s3", seq: 4, role: "assistant", created_at: "t",
        content: { text: "子总结", tool_calls: [], tool_results: [], parent_call_id: "task1" } },
      { id: "t1", seq: 5, role: "tool", created_at: "t", content: {
        text: "", tool_calls: [], tool_results: [{ call_id: "task1", content: "子总结", is_error: false }],
      } },
      { id: "a2", seq: 6, role: "assistant", created_at: "t",
        content: { text: "主回答", tool_calls: [], tool_results: [] } },
    ]
    const blocks = messagesToTurns(messages)[0].blocks
    expect(blocks.map((b) => b.kind)).toEqual(["subagent", "text"]) // 子消息不在顶层
    const card = asSub(blocks[0])
    expect(card.description).toBe("查战况")
    expect(card.prompt).toBe("查今天比分") // A:prompt 从 task args
    // B:卡内部重建出子 agent 过程(web_search 工具 + 子总结),而非只有结果文本
    expect(card.blocks.map((b) => b.kind)).toEqual(["tool", "text"])
    const subTool = card.blocks[0] as Extract<Block, { kind: "tool" }>
    expect(subTool.call.name).toBe("web_search")
    expect(subTool.result?.content).toBe("搜索结果") // 子 tool 结果回填
  })

  it("messagesToTurns:旧数据(子过程未落库)→ subagent 卡回退到结果文本", () => {
    const messages: Message[] = [
      { id: "a1", seq: 0, role: "assistant", created_at: "t", content: {
        text: "", tool_results: [],
        tool_calls: [{ id: "task1", name: "task", arguments: { description: "x", prompt: "p" } }],
      } },
      { id: "t1", seq: 1, role: "tool", created_at: "t", content: {
        text: "", tool_calls: [], tool_results: [{ call_id: "task1", content: "最终结果", is_error: false }],
      } },
    ]
    const card = asSub(messagesToTurns(messages)[0].blocks[0])
    expect(card.blocks).toHaveLength(1) // 无子消息 → 回退到结果文本(兼容阶段 1 历史)
    expect(card.blocks[0]).toMatchObject({ kind: "text", text: "最终结果" })
  })
})
