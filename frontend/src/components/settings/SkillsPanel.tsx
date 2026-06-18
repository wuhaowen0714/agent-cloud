import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "../../api/client"
import { skillDescription } from "../../skillText"
import { useStore } from "../../store"
import { SettingGroup, SettingRow } from "../ui"

// 技能库:内置技能(source=registry)由后端自动安装与维护,不可删——删了前端无入口
// 装回(手动 registry 安装界面已砍);uploaded/workspace 来源仍可删。
export function SkillsPanel() {
  const userId = useStore((s) => s.userId)!
  const qc = useQueryClient()

  const { data: pool = [] } = useQuery({
    queryKey: ["skills", userId],
    queryFn: () => api.listSkills(),
  })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["skills", userId] })
    qc.invalidateQueries({ queryKey: ["agentSkills"] })
  }
  const remove = useMutation({ mutationFn: (id: string) => api.deleteSkill(id), onSuccess: refresh })

  return (
    <div className="space-y-5">
      <SettingGroup label="已安装">
        {pool.length === 0 ? (
          <div className="px-3.5 py-4 text-center text-xs text-slate-400">还没有安装技能</div>
        ) : (
          pool.map((sk) => (
            <SettingRow key={sk.id} label={sk.name} hint={skillDescription(sk)}>
              {sk.source === "registry" ? (
                <span className="shrink-0 text-xs text-slate-300">内置</span>
              ) : (
                <button
                  className="shrink-0 text-xs text-slate-400 transition hover:text-red-600"
                  onClick={() => remove.mutate(sk.id)}
                >
                  删除
                </button>
              )}
            </SettingRow>
          ))
        )}
      </SettingGroup>
    </div>
  )
}
