import { useQuery } from "@tanstack/react-query"
import { Folder, Sparkles, Wrench } from "lucide-react"
import { useRef, useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"
import { SkillsMenu } from "./toggles/SkillsMenu"
import { ToolsMenu } from "./toggles/ToolsMenu"
import { TogglePopover } from "./toggles/TogglePopover"

// 图标+文字的描边 chip:纯灰图标按钮太隐蔽(用户反馈「很容易忽略」),
// 文字标签 + 边框白底让入口在顶栏上有明确的按钮形态。
const CHIP_BTN =
  "flex h-7 shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 " +
  "text-xs font-medium text-slate-600 shadow-sm transition " +
  "hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 " +
  "disabled:cursor-default disabled:opacity-40 disabled:hover:border-slate-200 " +
  "disabled:hover:bg-white disabled:hover:text-slate-600"

// 主区顶栏(仿 Claude Code):左侧 agent/会话 面包屑;右侧 工具/技能 开关入口 + 工作区文件。
// 认证后常驻——文件抽屉是用户级工作区,与是否选中会话无关,入口要始终可达。
export function TopBar() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const sessionId = useStore((s) => s.sessionId)
  const toggleFileDrawer = useStore((s) => s.toggleFileDrawer)
  // 工具/技能弹层:一次只开一个;无选中 agent 时按钮禁用(开关是 per-agent 的)
  const [open, setOpen] = useState<"tools" | "skills" | null>(null)
  const toolsBtn = useRef<HTMLButtonElement>(null)
  const skillsBtn = useRef<HTMLButtonElement>(null)

  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })
  const { data: sessions = [] } = useQuery({
    queryKey: ["sessions", userId],
    queryFn: () => api.listSessions(),
    enabled: !!userId,
  })

  const agent = agents.find((a) => a.id === agentId)
  const session = sessions.find((s) => s.id === sessionId)
  const sessionLabel = session ? (session.title ?? `会话 ${session.id.slice(0, 6)}`) : null

  return (
    <header className="flex shrink-0 items-center gap-2 border-b border-slate-200 bg-white/80 px-4 py-2 backdrop-blur">
      <div className="flex min-w-0 flex-1 items-center gap-1.5 text-sm">
        {agent && <span className="min-w-0 truncate text-slate-500">{agent.name}</span>}
        {agent && sessionLabel && <span className="shrink-0 text-slate-300">/</span>}
        {sessionLabel && <span className="truncate font-medium text-slate-800">{sessionLabel}</span>}
      </div>
      <button
        ref={toolsBtn}
        type="button"
        disabled={!agent}
        title={agent ? "工具" : "先选择 agent"}
        aria-label="工具"
        onClick={() => setOpen(open === "tools" ? null : "tools")}
        className={CHIP_BTN}
      >
        <Wrench size={14} className="text-slate-400" />
        <span className="hidden sm:inline">工具</span>
      </button>
      <button
        ref={skillsBtn}
        type="button"
        disabled={!agent}
        title={agent ? "技能" : "先选择 agent"}
        aria-label="技能"
        onClick={() => setOpen(open === "skills" ? null : "skills")}
        className={CHIP_BTN}
      >
        <Sparkles size={14} className="text-slate-400" />
        <span className="hidden sm:inline">技能</span>
      </button>
      <button
        type="button"
        title="工作区文件"
        aria-label="工作区文件"
        onClick={toggleFileDrawer}
        className={CHIP_BTN}
      >
        <Folder size={14} className="text-slate-400" />
        {/* 窄屏退化回纯图标:三 chip shrink-0,不退化会把面包屑挤没、裁掉文件入口 */}
        <span className="hidden sm:inline">文件</span>
      </button>
      {open === "tools" && agent && (
        <TogglePopover anchorRef={toolsBtn} title="工具" onClose={() => setOpen(null)}>
          <ToolsMenu agent={agent} />
        </TogglePopover>
      )}
      {open === "skills" && agent && (
        <TogglePopover anchorRef={skillsBtn} title="技能" onClose={() => setOpen(null)}>
          <SkillsMenu agentId={agent.id} />
        </TogglePopover>
      )}
    </header>
  )
}
