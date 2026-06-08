import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "../../api/client"
import { useStore } from "../../store"

export function SkillsPanel() {
  const userId = useStore((s) => s.userId)!
  const qc = useQueryClient()
  const [pick, setPick] = useState("")

  const { data: pool = [] } = useQuery({
    queryKey: ["skills", userId],
    queryFn: () => api.listSkills(userId),
  })
  const { data: registry = [] } = useQuery({ queryKey: ["registry"], queryFn: () => api.listRegistry() })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["skills", userId] })
    qc.invalidateQueries({ queryKey: ["agentSkills"] })
  }
  const install = useMutation({
    mutationFn: (name: string) => api.installSkill(userId, name),
    onSuccess: () => {
      setPick("")
      refresh()
    },
  })
  const remove = useMutation({ mutationFn: (id: string) => api.deleteSkill(id), onSuccess: refresh })

  const installed = new Set(pool.map((s) => s.name))
  const available = registry.filter((n) => !installed.has(n))

  return (
    <div className="space-y-4 text-sm">
      <div className="space-y-1">
        <div className="font-medium text-slate-700">已安装</div>
        {pool.length === 0 && <div className="text-xs text-slate-400">还没有安装技能</div>}
        {pool.map((sk) => (
          <div key={sk.id} className="flex items-center gap-2 rounded border border-slate-200 px-2 py-1">
            <span className="min-w-0 flex-1 truncate">
              <span className="text-slate-700">{sk.name}</span>
              <span className="ml-2 text-xs text-slate-400">{sk.description}</span>
            </span>
            <button className="shrink-0 text-xs text-slate-400 hover:text-red-600" onClick={() => remove.mutate(sk.id)}>
              删除
            </button>
          </div>
        ))}
      </div>
      <div className="space-y-1">
        <div className="font-medium text-slate-700">从 registry 安装</div>
        <div className="flex gap-2">
          <select
            className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
            value={pick}
            onChange={(e) => setPick(e.target.value)}
          >
            <option value="">选择技能…</option>
            {available.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          <button
            className="shrink-0 rounded bg-brand-600 px-3 py-1 text-sm text-white hover:bg-brand-700 disabled:opacity-40"
            disabled={!pick || install.isPending}
            onClick={() => install.mutate(pick)}
          >
            安装
          </button>
        </div>
        {available.length === 0 && registry.length > 0 && (
          <div className="text-xs text-slate-400">registry 里的技能都装好了</div>
        )}
      </div>
    </div>
  )
}
