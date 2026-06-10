import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "../../api/client"
import { useStore } from "../../store"
import type { Skill } from "../../types"
import { Switch } from "../ui"

// TopBar「技能」弹层:checked = agent 启用集,切换 = PUT 全量替换(即点即存)。
// 乐观更新 ["agentSkills", agentId],设置页与本弹层共用该缓存。
export function SkillsMenu({ agentId }: { agentId: string }) {
  const userId = useStore((s) => s.userId)
  const qc = useQueryClient()

  const { data: pool = [] } = useQuery({
    queryKey: ["skills", userId],
    queryFn: () => api.listSkills(),
  })
  const enabledQ = useQuery({
    queryKey: ["agentSkills", agentId],
    queryFn: () => api.getAgentSkills(agentId),
  })
  const enabled = enabledQ.data ?? []
  const ids = new Set(enabled.map((s) => s.id))

  const put = useMutation({
    mutationFn: (skillIds: string[]) => api.setAgentSkills(agentId, skillIds),
    onMutate: async (skillIds) => {
      await qc.cancelQueries({ queryKey: ["agentSkills", agentId] })
      const prev = qc.getQueryData<Skill[]>(["agentSkills", agentId])
      const set = new Set(skillIds)
      qc.setQueryData<Skill[]>(["agentSkills", agentId], pool.filter((s) => set.has(s.id)))
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(["agentSkills", agentId], ctx.prev)
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["agentSkills", agentId] }),
  })

  const toggle = (id: string) => {
    const next = new Set(ids)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    put.mutate([...next])
  }

  if (pool.length === 0) {
    return <div className="px-2.5 py-3 text-center text-xs text-slate-400">技能池为空</div>
  }
  // 启用集没回来前不渲染开关:此时全显「关」是假状态,一次点击的 PUT 全量替换
  // 会把真实启用集静默清空(审查 M2)
  if (enabledQ.isPending) {
    return <div className="px-2.5 py-3 text-center text-xs text-slate-400">加载中…</div>
  }
  return (
    <div>
      {pool.map((sk) => (
        <div key={sk.id} className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 hover:bg-slate-50">
          <div className="min-w-0 flex-1">
            <div className="text-xs font-medium text-slate-700">{sk.name}</div>
            <div className="truncate text-[11px] text-slate-400">{sk.description}</div>
          </div>
          <Switch checked={ids.has(sk.id)} onChange={() => toggle(sk.id)} label={sk.name} />
        </div>
      ))}
    </div>
  )
}
