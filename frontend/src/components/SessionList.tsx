import { useQuery } from "@tanstack/react-query"
import { api } from "../api/client"
import { useStore } from "../store"

export function SessionList() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const sessionId = useStore((s) => s.sessionId)
  const setSession = useStore((s) => s.setSession)

  const { data: sessions = [] } = useQuery({
    queryKey: ["sessions", userId],
    queryFn: () => api.listSessions(),
    enabled: !!userId,
  })
  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })

  const current = agents.find((a) => a.id === agentId)
  // 只显示当前 agent 的会话(会话本身带 agent_config_id);未选 agent 则为空。
  const mine = agentId ? sessions.filter((s) => s.agent_config_id === agentId) : []

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="mb-1 truncate px-1 text-xs font-medium tracking-wide text-slate-400">
        {current ? (
          <>
            <span className="text-slate-600">{current.name}</span> 的对话
          </>
        ) : (
          "对话"
        )}
      </div>
      <ul className="min-h-0 flex-1 space-y-0.5 overflow-auto">
        {mine.map((s) => (
          <li key={s.id}>
            <button
              className={`w-full truncate rounded-lg px-2.5 py-2 text-left text-sm transition ${
                s.id === sessionId
                  ? "bg-brand-50 font-medium text-brand-800"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
              onClick={() => setSession(s.id)}
            >
              {s.title ?? `会话 ${s.id.slice(0, 6)}`}
            </button>
          </li>
        ))}
        {agentId && mine.length === 0 && (
          <li className="px-2 py-6 text-center text-xs text-slate-400">还没有对话</li>
        )}
        {!agentId && (
          <li className="px-2 py-6 text-center text-xs text-slate-400">先选一个 agent</li>
        )}
      </ul>
    </div>
  )
}
