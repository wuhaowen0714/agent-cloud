import type { SettingsTab } from "../../store"

export interface StatusInfo {
  agentName: string | null
  model: string | null
  provider: string | null
  sessionTitle: string | null
  sessionIdShort: string | null
  messageCount: number
  contextTokens: number | null // 最近一回合 worker 报告的上下文占用;未跑过回合则 null
}

// compact 结果四态:压缩了 / 没东西可压 / 会话忙(回合进行中) / 出错。
export type CompactResult = "compacted" | "nothing" | "busy" | "error"

// 命令执行时拿到的上下文:动作接到 store/api/queryClient(在 useSlashCommands 里装配)。
export interface SlashContext {
  newSession: () => Promise<boolean> // false = 当前无 agent,未执行
  setModel: (model: string) => Promise<boolean> // 同上
  compact: () => Promise<CompactResult>
  modelSuggestions: () => string[]
  status: () => StatusInfo
  openSettings: (tab: SettingsTab) => void
  notify: (msg: string) => void // 一行 flash
  showStatus: () => void
  showHelp: () => void
}

export interface SlashCommand {
  name: string // 不含斜杠
  aliases?: string[]
  title: string
  hint: string
  needsArg?: boolean // true → 选中后进参数模式,不立即执行
  run?: (ctx: SlashContext) => void | Promise<void>
  suggestions?: (ctx: SlashContext, arg: string) => string[]
  runWithArg?: (ctx: SlashContext, arg: string) => void | Promise<void>
}

export function dedupeModels(models: (string | null | undefined)[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const m of models) {
    const t = m?.trim()
    if (t && !seen.has(t)) {
      seen.add(t)
      out.push(t)
    }
  }
  return out
}

export const COMMANDS: SlashCommand[] = [
  {
    name: "compact",
    title: "压缩上下文",
    hint: "压缩当前会话",
    run: async (c) => {
      const r = await c.compact()
      c.notify(
        r === "compacted"
          ? "已压缩当前会话上下文"
          : r === "nothing"
            ? "暂无可压缩内容"
            : r === "busy"
              ? "会话正忙(回合进行中),稍后再试"
              : "压缩失败,请稍后再试",
      )
    },
  },
  { name: "status", title: "状态", hint: "agent / 会话 / 消息数", run: (c) => c.showStatus() },
  {
    name: "new",
    title: "新会话",
    hint: "用当前 agent 开新会话",
    run: async (c) => {
      c.notify((await c.newSession()) ? "已新建会话" : "请先选择一个 agent")
    },
  },
  {
    name: "model",
    title: "切换模型",
    hint: "改当前 agent 的模型",
    needsArg: true,
    suggestions: (c, arg) => c.modelSuggestions().filter((m) => m.startsWith(arg.trim())),
    runWithArg: async (c, arg) => {
      const m = arg.trim()
      if (!m) return
      try {
        c.notify((await c.setModel(m)) ? `已切换模型:${m}` : "请先选择一个 agent")
      } catch {
        c.notify("切换模型失败")
      }
    },
  },
  { name: "help", title: "帮助", hint: "列出全部命令", run: (c) => c.showHelp() },
  { name: "settings", title: "设置", hint: "打开 Agent 设置", run: (c) => c.openSettings("agent") },
  { name: "memory", title: "记忆", hint: "打开记忆设置", run: (c) => c.openSettings("memory") },
  { name: "skills", title: "技能", hint: "打开技能设置", run: (c) => c.openSettings("skills") },
  { name: "keys", title: "Provider Keys", hint: "打开 Key 设置", run: (c) => c.openSettings("keys") },
]

export type ParsedInput =
  | { mode: "command"; prefix: string }
  | { mode: "arg"; command: SlashCommand; arg: string }
  | { mode: "none" }

export function matchCommands(prefix: string): SlashCommand[] {
  return COMMANDS.filter(
    (c) => c.name.startsWith(prefix) || (c.aliases?.some((a) => a.startsWith(prefix)) ?? false),
  )
}

export function parseInput(text: string): ParsedInput {
  // 参数模式:带参命令 + 空格 + 余下任意(含空)。
  const argMatch = text.match(/^\/(\w+)\s([\s\S]*)$/)
  if (argMatch) {
    const cmd = COMMANDS.find(
      (c) => c.needsArg && (c.name === argMatch[1] || (c.aliases?.includes(argMatch[1]) ?? false)),
    )
    return cmd ? { mode: "arg", command: cmd, arg: argMatch[2] } : { mode: "none" }
  }
  // 命令模式:斜杠 + word 前缀(无空格、无第二个斜杠),且有命令匹配。
  const cmdMatch = text.match(/^\/(\w*)$/)
  if (cmdMatch && matchCommands(cmdMatch[1]).length > 0) {
    return { mode: "command", prefix: cmdMatch[1] }
  }
  return { mode: "none" }
}
