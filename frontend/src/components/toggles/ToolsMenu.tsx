import { useMutation, useQueryClient } from "@tanstack/react-query"
import { BUILTIN_TOOLS, checkedToEnabled, enabledToChecked } from "../../agentConfig"
import { api } from "../../api/client"
import { useStore } from "../../store"
import type { AgentConfig } from "../../types"
import { Switch } from "../ui"

// TopBar「工具」弹层:per-agent 即点即存(PATCH enabled_tools)。
// 与设置页是同一份数据的两个入口:乐观更新 ["agents"] 缓存,设置页打开即拿新值。
export function ToolsMenu({ agent }: { agent: AgentConfig }) {
  const userId = useStore((s) => s.userId)
  const qc = useQueryClient()
  const checked = enabledToChecked(agent.enabled_tools)

  const patch = useMutation({
    mutationFn: (enabled_tools: string[]) => api.patchAgent(agent.id, { enabled_tools }),
    onMutate: async (enabled_tools) => {
      await qc.cancelQueries({ queryKey: ["agents", userId] })
      const prev = qc.getQueryData<AgentConfig[]>(["agents", userId])
      qc.setQueryData<AgentConfig[]>(["agents", userId], (old = []) =>
        old.map((a) => (a.id === agent.id ? { ...a, enabled_tools } : a)),
      )
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(["agents", userId], ctx.prev)
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["agents", userId] }),
  })

  const toggle = (name: string) => {
    const next = new Set(checked)
    if (next.has(name)) next.delete(name)
    else next.add(name)
    // 全关 → checkedToEnabled 会规范化成 [](= 全部启用)而非「全禁」,
    // 即点即存下这是个反直觉陷阱:忽略关掉最后一个工具的点击。
    if (next.size === 0) return
    patch.mutate(checkedToEnabled(next))
  }

  return (
    <div>
      {BUILTIN_TOOLS.map((t) => (
        <div key={t.name} className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 hover:bg-slate-50">
          <div className="min-w-0 flex-1">
            <div className="font-mono text-xs text-slate-700">{t.name}</div>
            <div className="truncate text-[11px] text-slate-400">{t.desc}</div>
          </div>
          <Switch checked={checked.has(t.name)} onChange={() => toggle(t.name)} label={t.name} />
        </div>
      ))}
    </div>
  )
}
