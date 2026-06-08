import { useQuery } from "@tanstack/react-query"
import { api } from "../api/client"
import { useStore } from "../store"

export function SessionList() {
  const userId = useStore((s) => s.userId)
  const sessionId = useStore((s) => s.sessionId)
  const setSession = useStore((s) => s.setSession)

  const { data: sessions = [] } = useQuery({
    queryKey: ["sessions", userId],
    queryFn: () => api.listSessions(),
    enabled: !!userId,
  })

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="mb-1.5 px-1 text-xs font-medium uppercase tracking-wide text-slate-400">对话</div>
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
          <li className="px-2 py-6 text-center text-xs text-slate-400">还没有对话</li>
        )}
      </ul>
    </div>
  )
}
