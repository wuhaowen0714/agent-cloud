import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useEffect, useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"
import { AgentHeader } from "./AgentHeader"
import { AgentRail } from "./AgentRail"
import { SessionList } from "./SessionList"

/** 侧栏 = 左 46px AgentRail(只管切 agent)+ 右面板(当前 agent 的头部/新对话/会话列表)。
 * Sidebar 自身是组合器 + 两件协调事:rail 新建后让面板头部进改名态;自动落位。 */
export function Sidebar() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const sessionId = useStore((s) => s.sessionId)
  const setAgent = useStore((s) => s.setAgent)
  const setSession = useStore((s) => s.setSession)
  const qc = useQueryClient()
  // rail 新建 agent → 面板头部自动进入改名态(跨组件协调放在共同父级)
  const [autoRenameId, setAutoRenameId] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () => api.createSession({ agent_config_id: agentId! }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["sessions", userId] })
      setSession(s.id)
    },
  })

  const agentsQ = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })
  const agents = agentsQ.data ?? []
  const { data: sessions = [] } = useQuery({
    queryKey: ["sessions", userId],
    queryFn: () => api.listSessions(),
    enabled: !!userId,
  })

  // 自动落位:无选中 agent → 选第一个;选中后无会话 → 选该 agent 最近活跃的一条。
  // 新注册用户(注册播种 main+会话)登录即可直接打字;删除当前选中后的兜底也走这里。
  // 自愈:localStorage 残留的 agentId 指向已删 agent(他端删除/换号残留)→ 落回第一个,
  // 否则会停在「无高亮、列表空、新对话 404」的幽灵选中态。仅在 agents 加载成功后判定。
  useEffect(() => {
    if (!agentsQ.isSuccess) return
    if (!agentId && agents.length) setAgent(agents[0].id)
    else if (agentId && !agents.some((a) => a.id === agentId)) setAgent(agents[0]?.id ?? null)
  }, [agentId, agents, agentsQ.isSuccess, setAgent])
  useEffect(() => {
    if (!agentId || sessionId) return
    const mine = sessions
      .filter((s) => s.agent_config_id === agentId)
      .sort((a, b) => +new Date(b.last_active_at) - +new Date(a.last_active_at))
    if (mine.length) setSession(mine[0].id)
  }, [agentId, sessionId, sessions, setSession])

  return (
    <aside className="flex w-80 flex-none border-r border-slate-200">
      <AgentRail onCreated={setAutoRenameId} />
      <div className="flex min-w-0 flex-1 flex-col gap-3 bg-white/80 p-3 backdrop-blur-sm">
        {agentsQ.isSuccess && agents.length === 0 ? (
          <div className="flex flex-1 items-center justify-center px-4 text-center text-sm text-slate-400">
            在左栏 + 新建一个 Agent 开始
          </div>
        ) : (
          <>
            <AgentHeader
              autoRenameId={autoRenameId}
              onAutoRenameConsumed={() => setAutoRenameId(null)}
            />
            <button
              disabled={!agentId || create.isPending}
              onClick={() => create.mutate()}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand-50 px-3 py-2 text-sm font-medium text-brand-700 transition hover:bg-brand-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Plus size={16} />
              新对话
            </button>
            <SessionList />
          </>
        )}
      </div>
    </aside>
  )
}
