import { useQuery } from "@tanstack/react-query"
import { Plus, Settings2 } from "lucide-react"
import { api } from "../api/client"
import { useStore } from "../store"

/**
 * 侧栏的 agent 列表(替换原来的下拉切换器):agent 是一等导航项,直接点选,选中高亮,
 * 悬停/选中露出设置图标进设置。会话列表(SessionList)只显示当前选中 agent 的对话。
 */
export function AgentList() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const setAgent = useStore((s) => s.setAgent)
  const openSettings = useStore((s) => s.openSettings)

  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })

  const newAgent = () => {
    setAgent(null)
    openSettings()
  }

  return (
    <div className="flex flex-col">
      <div className="mb-1 flex items-center justify-between px-1">
        <span className="text-xs font-medium tracking-wide text-slate-400">Agents</span>
        <button
          className="flex h-5 w-5 items-center justify-center rounded-md text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
          title="新建 agent"
          aria-label="新建 agent"
          onClick={newAgent}
        >
          <Plus size={15} />
        </button>
      </div>

      {agents.length === 0 ? (
        <button
          className="rounded-lg border border-dashed border-slate-200 px-3 py-2 text-left text-xs text-slate-400 transition hover:border-slate-300 hover:text-slate-600"
          onClick={newAgent}
        >
          还没有 agent — 新建一个
        </button>
      ) : (
        <ul className="max-h-52 space-y-0.5 overflow-auto">
          {agents.map((a) => {
            const active = a.id === agentId
            return (
              <li
                key={a.id}
                className={`group flex items-center gap-1 rounded-lg pr-1 transition ${
                  active ? "bg-brand-50" : "hover:bg-slate-100"
                }`}
              >
                <button
                  className="flex min-w-0 flex-1 items-center px-2.5 py-2 text-left"
                  onClick={() => setAgent(a.id)}
                >
                  <span className="min-w-0 flex-1 truncate">
                    <span
                      className={`text-sm font-medium ${active ? "text-brand-800" : "text-slate-700"}`}
                    >
                      {a.name}
                    </span>
                    <span className="ml-1.5 text-xs text-slate-400">{a.model}</span>
                  </span>
                </button>
                <button
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-slate-400 transition hover:bg-white hover:text-slate-700 ${
                    active ? "opacity-100" : "opacity-0 group-hover:opacity-100"
                  }`}
                  title="agent 设置"
                  aria-label={`${a.name} 设置`}
                  onClick={() => {
                    setAgent(a.id)
                    openSettings()
                  }}
                >
                  <Settings2 size={14} />
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
