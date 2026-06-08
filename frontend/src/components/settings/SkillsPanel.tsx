import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "../../api/client"
import { useStore } from "../../store"
import { Button, Select } from "../ui"

export function SkillsPanel() {
  const userId = useStore((s) => s.userId)!
  const qc = useQueryClient()
  const [pick, setPick] = useState("")

  const { data: pool = [] } = useQuery({
    queryKey: ["skills", userId],
    queryFn: () => api.listSkills(),
  })
  const { data: registry = [] } = useQuery({ queryKey: ["registry"], queryFn: () => api.listRegistry() })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["skills", userId] })
    qc.invalidateQueries({ queryKey: ["agentSkills"] })
  }
  const install = useMutation({
    mutationFn: (name: string) => api.installSkill(name),
    onSuccess: () => {
      setPick("")
      refresh()
    },
  })
  const remove = useMutation({ mutationFn: (id: string) => api.deleteSkill(id), onSuccess: refresh })

  const installed = new Set(pool.map((s) => s.name))
  const available = registry.filter((n) => !installed.has(n))

  return (
    <div className="space-y-5 text-sm">
      <div className="space-y-2">
        <div className="text-sm font-semibold text-slate-800">已安装</div>
        {pool.length === 0 && <div className="text-xs text-slate-400">还没有安装技能</div>}
        {pool.map((sk) => (
          <div
            key={sk.id}
            className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2.5 shadow-card"
          >
            <span className="min-w-0 flex-1 truncate">
              <span className="font-medium text-slate-700">{sk.name}</span>
              <span className="ml-2 text-xs text-slate-400">{sk.description}</span>
            </span>
            <button
              className="shrink-0 text-xs text-slate-400 transition hover:text-red-600"
              onClick={() => remove.mutate(sk.id)}
            >
              删除
            </button>
          </div>
        ))}
      </div>
      <div className="space-y-2">
        <div className="text-sm font-semibold text-slate-800">从 registry 安装</div>
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <Select value={pick} onChange={(e) => setPick(e.target.value)}>
              <option value="">选择技能…</option>
              {available.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </div>
          <Button onClick={() => install.mutate(pick)} disabled={!pick || install.isPending}>
            安装
          </Button>
        </div>
        {available.length === 0 && registry.length > 0 && (
          <div className="text-xs text-slate-400">registry 里的技能都装好了</div>
        )}
      </div>
    </div>
  )
}
