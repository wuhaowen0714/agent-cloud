import { useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "../api/client"
import { useStore } from "../store"
import { AccountMenu } from "./AccountMenu"
import { AgentSwitcher } from "./AgentSwitcher"
import { SessionList } from "./SessionList"

export function Sidebar() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const setSession = useStore((s) => s.setSession)
  const qc = useQueryClient()

  const create = useMutation({
    mutationFn: () => api.createSession({ agent_config_id: agentId! }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["sessions", userId] })
      setSession(s.id)
    },
  })

  return (
    <aside className="flex w-72 flex-col gap-3 border-r border-slate-200 bg-white p-3">
      {/* 品牌头 */}
      <div className="flex items-center gap-2 px-1 pt-1">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-600 text-sm font-bold text-white">
          A
        </span>
        <span className="text-sm font-semibold tracking-tight text-slate-800">Agent Cloud</span>
      </div>

      {/* 新对话(无 agent 时禁用)*/}
      <button
        className="w-full rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-40"
        disabled={!agentId || create.isPending}
        title={agentId ? "" : "先选择 / 新建一个 agent"}
        onClick={() => create.mutate()}
      >
        ＋ 新对话
      </button>

      {/* agent 切换器 */}
      <AgentSwitcher />

      {/* 对话列表(占据剩余高度)*/}
      <SessionList />

      {/* 贴底账户区 */}
      <AccountMenu />
    </aside>
  )
}
