import type { Message, ToolCall, ToolResult } from "./types"

// 一个回合(turn)按【时间顺序】拆成的展示块:思考 / 正文 / 工具调用(含结果)。
// live 流式与已落库历史都归一成 Block[],用同一个渲染器 → 顺序一致、回合结束刷新历史时不突变。
// 参数生成中的进度(tool 块的 pending 态;tool_call_start 升级真卡时清掉)
export interface ToolProgress { argsChars: number; lines: number; path: string }

export type Block =
  | { kind: "thinking"; id: string; text: string }
  | { kind: "text"; id: string; text: string }
  | { kind: "tool"; id: string; call: ToolCall; result?: ToolResult; progress?: ToolProgress }

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
// 已有同 id 的 pending 进度卡(参数生成期间建的)→ 原位替换为真卡:保位置不闪跳,progress 清掉。
export function appendToolCall(blocks: Block[], call: ToolCall): Block[] {
  const i = blocks.findIndex((b) => b.kind === "tool" && b.id === call.id)
  if (i === -1) return [...blocks, { kind: "tool", id: call.id, call }]
  return [...blocks.slice(0, i), { kind: "tool", id: call.id, call }, ...blocks.slice(i + 1)]
}

// 流式:参数生成进度 upsert。已升级真卡 → 忽略迟到进度(原引用,零渲染);
// 已有 pending 卡 → 原位更新计数;否则尾部新开 pending 卡(参数未知,先空 {})。
export function upsertToolProgress(
  blocks: Block[],
  p: { call_id: string; tool: string; args_chars: number; lines: number; path: string },
): Block[] {
  const progress = { argsChars: p.args_chars, lines: p.lines, path: p.path }
  const i = blocks.findIndex((b) => b.kind === "tool" && b.id === p.call_id)
  if (i === -1) {
    return [
      ...blocks,
      { kind: "tool", id: p.call_id, call: { id: p.call_id, name: p.tool, arguments: {} }, progress },
    ]
  }
  const b = blocks[i] as Extract<Block, { kind: "tool" }>
  if (!b.progress) return blocks
  return [...blocks.slice(0, i), { ...b, progress }, ...blocks.slice(i + 1)]
}

// 终态(error/cancel):回合流已死,不会再有 tool_call_start 升级 pending 卡——剥掉它们,
// 避免对已死回合显示"仍在运行"的旋转指示;其余块保留(error 不清半截文本是既有有意行为)。
export function dropPendingTools(blocks: Block[]): Block[] {
  return blocks.filter((b) => !(b.kind === "tool" && b.progress))
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
