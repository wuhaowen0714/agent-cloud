import type { Message, ToolCall, ToolResult } from "./types"

// 一个回合(turn)按【时间顺序】拆成的展示块:思考 / 正文 / 工具调用(含结果)。
// live 流式与已落库历史都归一成 Block[],用同一个渲染器 → 顺序一致、回合结束刷新历史时不突变。
export type Block =
  | { kind: "thinking"; id: string; text: string }
  | { kind: "text"; id: string; text: string }
  | { kind: "tool"; id: string; call: ToolCall; result?: ToolResult }

// 流式:把思考/正文增量并入 blocks。尾块同类则追加,否则新开一块 → 还原模型真实时序。
// 返回新数组(不可变,触发 React 更新)。
export function appendDelta(blocks: Block[], kind: "thinking" | "text", text: string): Block[] {
  const last = blocks[blocks.length - 1]
  if (last && last.kind === kind) {
    return [...blocks.slice(0, -1), { ...last, text: last.text + text }]
  }
  return [...blocks, { kind, id: `${kind}-${blocks.length}`, text }]
}

// 流式:工具调用就地新开一块(以 call.id 为 key,稍后由结果回填)。
export function appendToolCall(blocks: Block[], call: ToolCall): Block[] {
  return [...blocks, { kind: "tool", id: call.id, call }]
}

// 流式:工具结果按 call_id 配对回填到对应的工具块(位置不变)。
export function attachToolResult(blocks: Block[], callId: string, result: ToolResult): Block[] {
  return blocks.map((b) => (b.kind === "tool" && b.call.id === callId ? { ...b, result } : b))
}

// 历史里一个回合:可能有用户消息(userText),以及该回合的展示块。
export interface Turn {
  id: string
  userText: string | null
  blocks: Block[]
}

// 历史:把按 seq 排序的消息分组成「回合」。user 消息开启一个新回合;其后的 assistant/tool
// 消息都归入该回合,直到下一条 user 消息。每个回合内按消息顺序展开成 Block[]:
// assistant 消息 → 正文块 + 各工具调用块;tool 消息 → 结果按 call_id 配对回填到工具块。
// 思考不落库,故历史里没有思考块(仅 live 流式期间可见)。
export function messagesToTurns(messages: Message[]): Turn[] {
  const turns: Turn[] = []
  let cur: { id: string; user: string | null; assistants: Message[]; results: Map<string, ToolResult> } | null = null

  const flush = () => {
    if (!cur) return
    const blocks: Block[] = []
    for (const m of cur.assistants) {
      if (m.content.text) blocks.push({ kind: "text", id: `${m.id}-text`, text: m.content.text })
      for (const c of m.content.tool_calls) {
        blocks.push({ kind: "tool", id: c.id, call: c, result: cur.results.get(c.id) })
      }
    }
    turns.push({ id: cur.id, userText: cur.user, blocks })
    cur = null
  }

  for (const m of messages) {
    if (m.role === "user") {
      flush()
      cur = { id: m.id, user: m.content.text, assistants: [], results: new Map() }
    } else {
      if (!cur) cur = { id: m.id, user: null, assistants: [], results: new Map() }
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
