import type { Message, ToolCall, ToolResult, TurnEvent } from "./types"

// 一个回合(turn)按【时间顺序】拆成的展示块:思考 / 正文 / 工具调用(含结果)。
// live 流式与已落库历史都归一成 Block[],用同一个渲染器 → 顺序一致、回合结束刷新历史时不突变。
// 参数生成中的进度(tool 块的 pending 态;tool_call_start 升级真卡时清掉)
export interface ToolProgress { argsChars: number; lines: number; path: string }

export type Block =
  | { kind: "thinking"; id: string; text: string }
  | { kind: "text"; id: string; text: string }
  | { kind: "tool"; id: string; call: ToolCall; result?: ToolResult; progress?: ToolProgress }
  // 子 agent(task 派生):同 subagent_id 的事件收拢进内部 blocks,渲染成折叠卡片。
  | { kind: "subagent"; id: string; description: string; prompt: string; blocks: Block[]; running: boolean; ok: boolean }

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

// 把一个流事件应用到一组 blocks(顶层与 subagent 内部共用)。非 block 类事件
// (turn_done/error/reset/subagent_*)由调用方单独处理,这里原样返回。
export function applyEvent(blocks: Block[], e: TurnEvent): Block[] {
  switch (e.type) {
    case "thinking_delta":
      return appendDelta(blocks, "thinking", e.text)
    case "text_delta":
      return appendDelta(blocks, "text", e.text)
    case "tool_call_progress":
      return upsertToolProgress(blocks, e)
    case "tool_call_start":
      // task 由 subagent_started 承载成子 agent 卡片,顶层不再建工具卡 —— 否则 live 会把一次
      // task 画成 ToolCallCard + SubagentCard 两张,且回合结束刷历史时跳变成一张(历史只有
      // subagent 卡)。对应的 tool_result 因顶层无此 task 块,attachToolResult 原样返回、无害。
      if (e.tool === "task") return blocks
      return appendToolCall(blocks, { id: e.call_id, name: e.tool, arguments: e.args })
    case "tool_result":
      return attachToolResult(blocks, e.call_id, {
        call_id: e.call_id,
        content: e.result,
        is_error: e.is_error,
      })
    default:
      return blocks
  }
}

// 子 agent 开始:新开一个 subagent 块(幂等;同 id 已存在则不重开)。
export function startSubagent(
  blocks: Block[], id: string, description: string, prompt: string,
): Block[] {
  if (blocks.some((b) => b.kind === "subagent" && b.id === id)) return blocks
  return [
    ...blocks,
    { kind: "subagent", id, description, prompt, blocks: [], running: true, ok: true },
  ]
}

// 子 agent 事件:应用到对应 subagent 块的内部 blocks(找不到该 id 则原样返回)。
export function appendToSubagent(blocks: Block[], id: string, e: TurnEvent): Block[] {
  return blocks.map((b) =>
    b.kind === "subagent" && b.id === id ? { ...b, blocks: applyEvent(b.blocks, e) } : b,
  )
}

// 子 agent 结束:标记 running=false + ok(是否自动折叠由渲染层依 running 决定)。
export function finishSubagent(blocks: Block[], id: string, ok: boolean): Block[] {
  return blocks.map((b) =>
    b.kind === "subagent" && b.id === id ? { ...b, running: false, ok } : b,
  )
}

// 历史里一个回合:可能有用户消息(userText),以及该回合的展示块。
export interface Turn {
  id: string
  userText: string | null
  userAt: string | null // user 消息时间(提问气泡下显示)
  doneAt: string | null // 回合最后一条 assistant/tool 消息时间 = 回答完成时间
  blocks: Block[]
}

// 历史:把按 seq 排序的消息分组成「回合」。user 消息开启一个新回合;其后的 assistant/tool
// 消息都归入该回合,直到下一条 user 消息。每个回合内按消息顺序展开成 Block[]:
// assistant 消息 → 正文块 + 各工具调用块;tool 消息 → 结果按 call_id 配对回填到工具块。
// 思考不落库,故历史里没有思考块(仅 live 流式期间可见)。
// 把一组消息(按顺序的 assistant/tool)重建成展示块:assistant → 正文 + 工具块;tool → 结果按
// call_id 回填。task 工具调用渲染成折叠 subagent 卡:内部 blocks 由 parent_call_id=call_id 的子
// 消息(subByCall)递归重建;子过程未落库的旧数据回退到结果文本。子消息无 task,递归止于一层。
function rebuildBlocks(msgs: Message[], subByCall: Map<string, Message[]>): Block[] {
  const results = new Map<string, ToolResult>()
  for (const m of msgs) {
    if (m.role === "tool") for (const r of m.content.tool_results) results.set(r.call_id, r)
  }
  const blocks: Block[] = []
  for (const m of msgs) {
    if (m.role === "tool") continue
    if (m.content.text) blocks.push({ kind: "text", id: `${m.id}-text`, text: m.content.text })
    for (const c of m.content.tool_calls) {
      if (c.name === "task") {
        const r = results.get(c.id)
        const desc = (c.arguments as { description?: unknown }).description
        const prompt = (c.arguments as { prompt?: unknown }).prompt
        const subMsgs = subByCall.get(c.id) ?? []
        // 子过程已落库 → 重建子 blocks;旧数据(子过程未落库)→ 回退到结果文本。
        const inner: Block[] = subMsgs.length
          ? rebuildBlocks(subMsgs, subByCall)
          : r
            ? [{ kind: "text", id: `${c.id}-r`, text: r.content }]
            : []
        blocks.push({
          kind: "subagent",
          id: c.id,
          description: typeof desc === "string" ? desc : "子任务",
          prompt: typeof prompt === "string" ? prompt : "",
          blocks: inner,
          running: false,
          ok: !(r?.is_error ?? false),
        })
      } else {
        blocks.push({ kind: "tool", id: c.id, call: c, result: results.get(c.id) })
      }
    }
  }
  return blocks
}

export function messagesToTurns(messages: Message[]): Turn[] {
  // 子 agent 消息(parent_call_id 非空)先按 parent_call_id 分组、从主序列剔除:它们不参与回合
  // 分组,而是重建进对应 task 的 subagent 卡。思考不落库,故历史里没有思考块。
  const subByCall = new Map<string, Message[]>()
  const mains: Message[] = []
  for (const m of messages) {
    const pid = m.content.parent_call_id
    if (pid) {
      const arr = subByCall.get(pid) ?? []
      arr.push(m)
      subByCall.set(pid, arr)
    } else {
      mains.push(m)
    }
  }

  const turns: Turn[] = []
  let cur: {
    id: string; user: string | null; userAt: string | null; lastAt: string | null; msgs: Message[]
  } | null = null

  const flush = () => {
    if (!cur) return
    turns.push({
      id: cur.id, userText: cur.user, userAt: cur.userAt, doneAt: cur.lastAt,
      blocks: rebuildBlocks(cur.msgs, subByCall),
    })
    cur = null
  }

  for (const m of mains) {
    if (m.role === "user") {
      flush()
      cur = { id: m.id, user: m.content.text, userAt: m.created_at, lastAt: null, msgs: [] }
    } else {
      if (!cur) cur = { id: m.id, user: null, userAt: null, lastAt: null, msgs: [] }
      cur.lastAt = m.created_at // 回合内任何 assistant/tool 消息都推进「完成时间」
      cur.msgs.push(m)
    }
  }
  flush()
  return turns
}
