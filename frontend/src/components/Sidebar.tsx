import { useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "../api/client"
import { useStore } from "../store"
import { AccountMenu } from "./AccountMenu"
import { AgentList } from "./AgentList"
import { SessionList } from "./SessionList"
import { Button } from "./ui"

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
    <aside className="flex w-72 flex-col gap-3 border-r border-slate-200 bg-white/80 p-3 backdrop-blur-sm">
      {/* 品牌头 */}
      <div className="flex items-center gap-2.5 px-1 pt-1">
        <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-600 text-sm font-bold text-white shadow-sm">
          A
        </span>
        <span className="text-[15px] font-semibold tracking-tight text-slate-800">Agent Cloud</span>
      </div>

      {/* 新对话(无 agent 时禁用)*/}
      <Button
        className="w-full"
        disabled={!agentId || create.isPending}
        title={agentId ? "" : "先选择 / 新建一个 agent"}
        onClick={() => create.mutate()}
      >
        ＋ 新对话
      </Button>

      {/* agent 列表(直接点选,无下拉)*/}
      <AgentList />

      {/* 当前 agent 的对话列表(占据剩余高度)*/}
      <SessionList />

      {/* 贴底账户区 */}
      <AccountMenu />
    </aside>
  )
}
