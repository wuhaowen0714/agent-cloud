import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, Settings2 } from "lucide-react"
import { useState } from "react"
import { nextAgentName } from "../agentConfig"
import { api } from "../api/client"
import { DEFAULT_MODEL } from "../models"
import { useStore } from "../store"
import { RowMenu } from "./RowMenu"

/**
 * 侧栏 agent 列表:一等导航项,点选切换。底部幽灵行一键新建(默认名 Agent N,
 * 成功即选中并进入行内改名态);行尾 hover:⚙ 设置 + … 菜单(重命名 / 二次确认删除,
 * 删除连带该 agent 的全部会话,由后端保证)。
 */
export function AgentList() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const setAgent = useStore((s) => s.setAgent)
  const openSettings = useStore((s) => s.openSettings)
  const qc = useQueryClient()
  const [renamingId, setRenamingId] = useState<string | null>(null)

  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ["agents", userId] })

  const create = useMutation({
    mutationFn: () =>
      api.createAgent({
        name: nextAgentName(agents.map((a) => a.name)),
        model: DEFAULT_MODEL,
        provider: "openai",
      }),
    onSuccess: async (a) => {
      await invalidate()
      setAgent(a.id)
      setRenamingId(a.id) // 新建即改名:想改顺手改,不想改 Esc 留默认名
    },
  })

  const commitRename = async (id: string, value: string, original: string) => {
    const name = value.trim()
    setRenamingId(null)
    if (!name || name === original) return
    await api.patchAgent(id, { name })
    await invalidate()
  }

  const removeAgent = async (id: string) => {
    await api.deleteAgent(id) // 409 → 抛 HttpError,由 RowMenu 原位提示
    await invalidate()
    await qc.invalidateQueries({ queryKey: ["sessions", userId] })
    if (useStore.getState().agentId === id) {
      const rest = agents.filter((a) => a.id !== id)
      setAgent(rest[0]?.id ?? null)
    }
  }

  return (
    <div className="flex flex-col">
      <div className="mb-1 px-1 text-xs font-medium tracking-wide text-slate-400">Agents</div>

      <ul className="max-h-52 space-y-0.5 overflow-auto">
        {agents.map((a) => {
          const active = a.id === agentId
          return (
            <li
              key={a.id}
              className={`group flex items-center gap-1 rounded-lg pr-1 transition ${
                active ? "bg-brand-50" : "hover:bg-slate-100"
              }`}
            >
              {renamingId === a.id ? (
                <input
                  autoFocus
                  defaultValue={a.name}
                  aria-label={`重命名 ${a.name}`}
                  onFocus={(e) => e.target.select()}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void commitRename(a.id, e.currentTarget.value, a.name)
                    else if (e.key === "Escape") setRenamingId(null)
                  }}
                  onBlur={() => setRenamingId(null)}
                  className="mx-1 my-1 w-full rounded-lg border border-brand-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
                />
              ) : (
                <>
                  <button
                    className="flex min-w-0 flex-1 items-center px-2.5 py-2 text-left"
                    onClick={() => setAgent(a.id)}
                  >
                    <span className="min-w-0 flex-1 truncate">
                      <span
                        className={`text-sm font-medium ${active ? "text-brand-800" : "text-slate-700"}`}
                      >
                        {a.name}
                      </span>
                      <span className="ml-1.5 text-xs text-slate-400">{a.model}</span>
                    </span>
                  </button>
                  <button
                    className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-slate-400 transition hover:bg-white hover:text-slate-700 ${
                      active ? "opacity-100" : "opacity-0 group-hover:opacity-100"
                    }`}
                    title="agent 设置"
                    aria-label={`${a.name} 设置`}
                    onClick={() => {
                      setAgent(a.id)
                      openSettings()
                    }}
                  >
                    <Settings2 size={14} />
                  </button>
                  <RowMenu
                    ariaLabel={`${a.name} 更多操作`}
                    visible={active}
                    items={[
                      { label: "重命名", onSelect: () => setRenamingId(a.id) },
                      {
                        label: "删除",
                        danger: true,
                        confirmLabel: "连同全部会话删除?",
                        onSelect: () => removeAgent(a.id),
                      },
                    ]}
                  />
                </>
              )}
            </li>
          )
        })}
      </ul>

      <button
        disabled={create.isPending}
        onClick={() => create.mutate()}
        className="mt-1 flex w-full items-center gap-2 rounded-xl border border-slate-200 px-3 py-1.5 text-sm text-slate-500 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700 disabled:opacity-50"
      >
        <Plus size={15} className="text-slate-400" />
        新建 Agent
      </button>
    </div>
  )
}
