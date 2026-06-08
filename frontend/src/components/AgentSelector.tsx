import { useQuery } from "@tanstack/react-query"
import { api } from "../api/client"
import { useStore } from "../store"

export function AgentSelector() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const setAgent = useStore((s) => s.setAgent)
  const openSettings = useStore((s) => s.openSettings)

  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(userId!),
    enabled: !!userId,
  })

  if (!userId) return null
  return (
    <div className="flex items-center gap-1.5">
      <select
        className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
        value={agentId ?? ""}
        onChange={(e) => setAgent(e.target.value || null)}
      >
        <option value="">选择 agent…</option>
        {agents.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name} · {a.model}
          </option>
        ))}
      </select>
      <button
        className="shrink-0 rounded border border-slate-200 px-2 py-1 text-sm text-slate-500 hover:bg-slate-50 disabled:opacity-40"
        title="agent 设置"
        disabled={!agentId}
        onClick={openSettings}
      >
        ⚙
      </button>
      <button
        className="shrink-0 rounded border border-slate-200 px-2 py-1 text-sm text-slate-500 hover:bg-slate-50"
        title="新建 agent"
        onClick={() => {
          setAgent(null)
          openSettings()
        }}
      >
        ＋
      </button>
    </div>
  )
}
