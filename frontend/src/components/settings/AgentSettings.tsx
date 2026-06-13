import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { api } from "../../api/client"
import { useStore } from "../../store"
import { Button, Input, SettingGroup, SettingRow, Textarea } from "../ui"
import { MemoryPanel } from "./MemoryPanel"

export function AgentSettings() {
  const userId = useStore((s) => s.userId)!
  const agentId = useStore((s) => s.agentId)

  // 创建职责在侧栏 AgentRail(一键直创);设置页只编辑已选中的 agent。
  if (!agentId) {
    return (
      <div className="px-1 py-10 text-center text-sm text-slate-400">
        在左侧选择或新建一个 agent
      </div>
    )
  }
  return <AgentEditor key={agentId} agentId={agentId} userId={userId} />
}

function AgentEditor({ agentId, userId }: { agentId: string; userId: string }) {
  const qc = useQueryClient()
  const agentsQ = useQuery({ queryKey: ["agents", userId], queryFn: () => api.listAgents() })
  const agent = (agentsQ.data ?? []).find((a) => a.id === agentId)
  const docsQ = useQuery({
    queryKey: ["docs", "agent", agentId],
    queryFn: () => api.listDocs("agent", agentId),
  })
  const docs = docsQ.data ?? []

  // 模型/provider/凭据/思考档位已下放到 session(图一选择);设置页只编辑 agent 的
  // 名称 / 指令 / 记忆(工具/技能在顶栏弹层即点即存)。
  const [name, setName] = useState("")
  const [instructions, setInstructions] = useState("")
  const [saved, setSaved] = useState(false)

  const inited = useRef(false)
  useEffect(() => {
    if (inited.current || !agent || !docsQ.isSuccess) return
    setName(agent.name)
    setInstructions(docs.find((d) => d.type === "AGENTS")?.content ?? "")
    inited.current = true
  }, [agent, docs, docsQ.isSuccess])

  const hadAgentsDoc = docs.some((d) => d.type === "AGENTS")
  const save = useMutation({
    mutationFn: async () => {
      await api.patchAgent(agentId, { name })
      // 非空则写入;若原本有 AGENTS 文档则即使清空也写入(持久化"清空"),否则不创建空文档。
      if (instructions.trim() || hadAgentsDoc)
        await api.putDoc("agent", "AGENTS", instructions, agentId)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents", userId] })
      qc.invalidateQueries({ queryKey: ["docs", "agent", agentId] })
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    },
  })

  return (
    <div className="space-y-5">
      <SettingGroup label="基本">
        <SettingRow label="名称" block>
          <Input value={name} placeholder="名称" onChange={(e) => setName(e.target.value)} />
        </SettingRow>
      </SettingGroup>

      <SettingGroup label="指令(AGENTS)">
        <div className="p-3.5">
          <Textarea
            className="h-32 font-mono text-xs"
            placeholder="给这个 agent 的指令 / 人设(可选)"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
          />
        </div>
      </SettingGroup>

      <SettingGroup label="记忆(学到的)">
        <div className="p-3.5">
          <MemoryPanel
            scope="agent"
            agentId={agentId}
            hint="这个 agent 从对话学到的事实,≠ 上面的指令/人设。当前由你手动维护。"
          />
        </div>
      </SettingGroup>

      <div className="flex items-center gap-2 border-t border-slate-100 pt-4">
        <Button
          disabled={save.isPending || !name}
          title={!name ? "名称不能为空" : ""}
          onClick={() => save.mutate()}
        >
          {save.isPending ? "保存中…" : "保存"}
        </Button>
        {saved && <span className="text-xs font-medium text-brand-600">已保存 ✓</span>}
      </div>
    </div>
  )
}
