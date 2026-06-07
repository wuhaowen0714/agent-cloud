import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"

export function AgentSelector() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const setAgent = useStore((s) => s.setAgent)
  const qc = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ name: "", model: "", provider: "openai" })

  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(userId!),
    enabled: !!userId,
  })

  const create = useMutation({
    mutationFn: () => api.createAgent({ user_id: userId!, ...form }),
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["agents", userId] })
      setAgent(a.id)
      setCreating(false)
      setForm({ name: "", model: "", provider: "openai" })
    },
  })

  if (!userId) return null
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <select
          className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
          value={agentId ?? ""}
          onChange={(e) => setAgent(e.target.value || null)}
        >
          <option value="">选择 agent…</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>{a.name} · {a.model}</option>
          ))}
        </select>
        <button className="text-sm text-brand-700 hover:underline" onClick={() => setCreating((v) => !v)}>
          {creating ? "取消" : "+ 新建"}
        </button>
      </div>
      {creating && (
        <form
          className="space-y-1 rounded border border-slate-200 bg-white p-2"
          onSubmit={(e) => { e.preventDefault(); if (form.name && form.model) create.mutate() }}
        >
          {(["name", "model", "provider"] as const).map((k) => (
            <input
              key={k}
              className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
              placeholder={k === "model" ? "model(如 DeepSeek-V4-pro)" : k}
              value={form[k]}
              onChange={(e) => setForm({ ...form, [k]: e.target.value })}
            />
          ))}
          <button className="w-full rounded bg-brand-600 px-2 py-1 text-sm text-white hover:bg-brand-700">
            创建 agent
          </button>
        </form>
      )}
    </div>
  )
}
