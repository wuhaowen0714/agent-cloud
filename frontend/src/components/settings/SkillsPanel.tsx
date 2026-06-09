import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "../../api/client"
import { useStore } from "../../store"
import { Button, SelectMenu, SettingGroup, SettingRow } from "../ui"

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
    <div className="space-y-5">
      <SettingGroup label="已安装">
        {pool.length === 0 ? (
          <div className="px-3.5 py-4 text-center text-xs text-slate-400">还没有安装技能</div>
        ) : (
          pool.map((sk) => (
            <SettingRow key={sk.id} label={sk.name} hint={sk.description}>
              <button
                className="shrink-0 text-xs text-slate-400 transition hover:text-red-600"
                onClick={() => remove.mutate(sk.id)}
              >
                删除
              </button>
            </SettingRow>
          ))
        )}
      </SettingGroup>

      <SettingGroup label="从 registry 安装">
        <div className="space-y-2 p-3.5">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <SelectMenu
                value={pick}
                onChange={setPick}
                placeholder="选择技能…"
                options={available.map((n) => ({ value: n, label: n }))}
              />
            </div>
            <Button onClick={() => install.mutate(pick)} disabled={!pick || install.isPending}>
              安装
            </Button>
          </div>
          {available.length === 0 && registry.length > 0 && (
            <div className="text-xs text-slate-400">registry 里的技能都装好了</div>
          )}
        </div>
      </SettingGroup>
    </div>
  )
}
