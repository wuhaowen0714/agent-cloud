import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useEffect } from "react"
import { api } from "../api/client"
import { useStore } from "../store"
import { AccountMenu } from "./AccountMenu"
import { AgentList } from "./AgentList"
import { SessionList } from "./SessionList"

export function Sidebar() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const sessionId = useStore((s) => s.sessionId)
  const setAgent = useStore((s) => s.setAgent)
  const setSession = useStore((s) => s.setSession)
  const qc = useQueryClient()

  const create = useMutation({
    mutationFn: () => api.createSession({ agent_config_id: agentId! }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["sessions", userId] })
      setSession(s.id)
    },
  })

  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })
  const { data: sessions = [] } = useQuery({
    queryKey: ["sessions", userId],
    queryFn: () => api.listSessions(),
    enabled: !!userId,
  })
  // 自动落位:无选中 agent → 选第一个;选中后无会话 → 选该 agent 最近一条。
  // 新注册用户(注册播种 main+会话)登录即可直接打字;删除当前选中后的兜底也走这里。
  useEffect(() => {
    if (!agentId && agents.length) setAgent(agents[0].id)
  }, [agentId, agents, setAgent])
  useEffect(() => {
    if (!agentId || sessionId) return
    const mine = sessions.filter((s) => s.agent_config_id === agentId)
    if (mine.length) setSession(mine[mine.length - 1].id)
  }, [agentId, sessionId, sessions, setSession])

  return (
    <aside className="flex w-72 flex-col gap-3 border-r border-slate-200 bg-white/80 p-3 backdrop-blur-sm">
      {/* 品牌头 */}
      <div className="flex items-center gap-2.5 px-1 pt-1">
        <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-600 text-sm font-bold text-white shadow-sm">
          A
        </span>
        <span className="text-[15px] font-semibold tracking-tight text-slate-800">Agent Cloud</span>
      </div>

      {/* 新对话:幽灵行(无 agent 时禁用)*/}
      <button
        disabled={!agentId || create.isPending}
        title={agentId ? "" : "先选择 / 新建一个 agent"}
        onClick={() => create.mutate()}
        className="flex w-full items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-slate-200 disabled:hover:bg-transparent disabled:hover:text-slate-600"
      >
        <Plus size={16} className="text-slate-400" />
        新对话
      </button>

      {/* agent 列表(直接点选,无下拉)*/}
      <AgentList />

      {/* 当前 agent 的对话列表(占据剩余高度)*/}
      <SessionList />

      {/* 贴底账户区 */}
      <AccountMenu />
    </aside>
  )
}
