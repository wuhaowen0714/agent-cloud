import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "../api/client"
import { useStore } from "../store"

export function SessionList() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const sessionId = useStore((s) => s.sessionId)
  const setSession = useStore((s) => s.setSession)
  const qc = useQueryClient()

  const { data: sessions = [] } = useQuery({
    queryKey: ["sessions", userId],
    queryFn: () => api.listSessions(userId!),
    enabled: !!userId,
  })

  const create = useMutation({
    mutationFn: () => api.createSession({ user_id: userId!, agent_config_id: agentId! }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["sessions", userId] })
      setSession(s.id)
    },
  })

  if (!userId) return null
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-400">会话</span>
        <button
          className="rounded px-1.5 py-0.5 text-xs text-brand-700 enabled:hover:bg-brand-50 disabled:opacity-40"
          disabled={!agentId}
          title={agentId ? "" : "先选/建一个 agent"}
          onClick={() => create.mutate()}
        >
          ＋ 新会话
        </button>
      </div>
      <ul className="min-h-0 flex-1 space-y-0.5 overflow-auto">
        {sessions.map((s) => (
          <li key={s.id}>
            <button
              className={`w-full truncate rounded-md px-2 py-1.5 text-left text-sm ${
                s.id === sessionId
                  ? "bg-brand-50 font-medium text-brand-800 ring-1 ring-brand-100"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
              onClick={() => setSession(s.id)}
            >
              {s.title ?? `会话 ${s.id.slice(0, 6)}`}
            </button>
          </li>
        ))}
        {sessions.length === 0 && (
          <li className="px-2 py-1 text-xs text-slate-400">还没有会话</li>
        )}
      </ul>
    </div>
  )
}
