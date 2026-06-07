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
      <button
        className="mb-2 rounded border border-brand-600 px-2 py-1 text-sm text-brand-700 enabled:hover:bg-brand-50 disabled:opacity-40"
        disabled={!agentId}
        title={agentId ? "" : "先选/建一个 agent"}
        onClick={() => create.mutate()}
      >
        + 新会话
      </button>
      <ul className="min-h-0 flex-1 space-y-1 overflow-auto">
        {sessions.map((s) => (
          <li key={s.id}>
            <button
              className={`w-full truncate rounded px-2 py-1 text-left text-sm ${
                s.id === sessionId ? "bg-brand-100 text-brand-800" : "text-slate-600 hover:bg-slate-100"
              }`}
              onClick={() => setSession(s.id)}
            >
              {s.title ?? s.id.slice(0, 8)}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
