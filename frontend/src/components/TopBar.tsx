import { useQuery } from "@tanstack/react-query"
import { Folder } from "lucide-react"
import { api } from "../api/client"
import { useStore } from "../store"

// 主区顶栏(仿 Claude Code):左侧 agent/会话 面包屑,最右工作区文件按钮。
// 认证后常驻——文件抽屉是用户级工作区,与是否选中会话无关,入口要始终可达。
export function TopBar() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const sessionId = useStore((s) => s.sessionId)
  const toggleFileDrawer = useStore((s) => s.toggleFileDrawer)

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
        type="button"
        title="工作区文件"
        aria-label="工作区文件"
        onClick={toggleFileDrawer}
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
      >
        <Folder size={16} />
      </button>
    </header>
  )
}
