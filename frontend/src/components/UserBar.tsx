import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"

export function UserBar() {
  const userId = useStore((s) => s.userId)
  const setUser = useStore((s) => s.setUser)
  const [email, setEmail] = useState("")

  const { data: user } = useQuery({
    queryKey: ["user", userId],
    queryFn: () => api.getUser(userId!),
    enabled: !!userId,
  })

  if (userId) {
    return (
      <div className="flex items-center gap-2 text-sm">
        <span className="h-2 w-2 shrink-0 rounded-full bg-brand-500" />
        <span className="min-w-0 flex-1 truncate text-slate-600">{user?.email ?? userId}</span>
        <button
          className="shrink-0 text-xs text-slate-400 hover:text-slate-700"
          onClick={() => setUser(null)}
        >
          切换
        </button>
      </div>
    )
  }

  return (
    <form
      className="flex gap-2"
      onSubmit={async (e) => {
        e.preventDefault()
        if (!email.trim()) return
        const u = await api.createUser(email.trim())
        setUser(u.id)
      }}
    >
      <input
        className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
        placeholder="email 建/用 user"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <button className="rounded bg-brand-600 px-3 py-1 text-sm text-white hover:bg-brand-700">
        进入
      </button>
    </form>
  )
}
