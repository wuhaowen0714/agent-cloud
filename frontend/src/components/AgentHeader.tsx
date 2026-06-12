import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Settings2 } from "lucide-react"
import { useEffect, useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"
import { RowMenu } from "./RowMenu"

/** 面板头部:当前 agent 名 + 模型;hover 出 ⚙(设置)与 …(重命名/删除)——agent 的
 * 全部管理入口收在这里(rail 只管切换)。改名态:行内 input;autoRenameId 命中当前
 * agent(rail 新建后)自动进入。 */
export function AgentHeader({
  autoRenameId,
  onAutoRenameConsumed,
}: {
  autoRenameId: string | null
  onAutoRenameConsumed: () => void
}) {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const setAgent = useStore((s) => s.setAgent)
  const openSettings = useStore((s) => s.openSettings)
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)

  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })
  const agent = agents.find((a) => a.id === agentId)

  useEffect(() => {
    if (autoRenameId && autoRenameId === agentId) {
      setEditing(true)
      onAutoRenameConsumed()
    }
  }, [autoRenameId, agentId, onAutoRenameConsumed])

  if (!agent) return null
  const invalidate = () => qc.invalidateQueries({ queryKey: ["agents", userId] })

  const commitRename = async (value: string) => {
    const name = value.trim()
    setEditing(false)
    if (!name || name === agent.name) return
    try {
      await api.patchAgent(agent.id, { name })
      await invalidate()
    } catch {
      // 改名失败(网络/422):保持原名,不打断;maxLength 已挡住超长
    }
  }

  const removeAgent = async () => {
    await api.deleteAgent(agent.id) // 409(agent busy)→ 抛 HttpError,由 RowMenu 原位提示
    await invalidate()
    await qc.invalidateQueries({ queryKey: ["sessions", userId] })
    if (useStore.getState().agentId === agent.id) {
      // 从失效后的新鲜缓存取剩余(闭包里的 agents 是删除前的旧列表)
      const fresh = qc.getQueryData<typeof agents>(["agents", userId]) ?? []
      const rest = fresh.filter((a) => a.id !== agent.id)
      setAgent(rest[0]?.id ?? null)
    }
  }

  return (
    <div className="group">
      {editing ? (
        <input
          autoFocus
          defaultValue={agent.name}
          maxLength={200}
          aria-label={`重命名 ${agent.name}`}
          onFocus={(e) => e.target.select()}
          onKeyDown={(e) => {
            // isComposing:IME 选字的回车不算确认(否则中文名打一半就被提交)
            if (e.key === "Enter" && !e.nativeEvent.isComposing) void commitRename(e.currentTarget.value)
            else if (e.key === "Escape") setEditing(false)
          }}
          onBlur={() => setEditing(false)}
          className="w-full rounded-lg border border-brand-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
        />
      ) : (
        <div className="flex items-center gap-1">
          <span className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-800">
            {agent.name}
          </span>
          <button
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-slate-400 opacity-0 transition hover:bg-slate-100 hover:text-slate-700 group-hover:opacity-100"
            title="agent 设置"
            aria-label="agent 设置"
            onClick={() => openSettings()}
          >
            <Settings2 size={14} />
          </button>
          <RowMenu
            ariaLabel={`${agent.name} 更多操作`}
            items={[
              { label: "重命名", onSelect: () => setEditing(true) },
              {
                label: "删除",
                danger: true,
                confirmLabel: "连同全部会话删除?",
                onSelect: removeAgent,
              },
            ]}
          />
        </div>
      )}
      <div className="truncate px-0.5 text-xs text-slate-400">{agent.model}</div>
    </div>
  )
}
