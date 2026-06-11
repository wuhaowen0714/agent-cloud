import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { api } from "../../api/client"
import { useStore } from "../../store"
import { ModelMenu } from "../model/ModelMenu"
import {
  Button,
  Input,
  Segmented,
  SelectMenu,
  SettingGroup,
  SettingRow,
  Textarea,
} from "../ui"
import { MemoryPanel } from "./MemoryPanel"

export function AgentSettings() {
  const userId = useStore((s) => s.userId)!
  const agentId = useStore((s) => s.agentId)

  // 创建职责在侧栏 AgentList(一键直创);设置页只编辑已选中的 agent。
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
  const { data: creds = [] } = useQuery({
    queryKey: ["credentials", userId],
    queryFn: () => api.listCredentials(),
  })

  const [form, setForm] = useState({ name: "", model: "", provider: "", thinking_level: "", key_ref: "" })
  const [instructions, setInstructions] = useState("")
  const [saved, setSaved] = useState(false)

  // 仅在数据【首次加载完成】时灌一次本地草稿;之后的 refetch 不覆盖正在编辑的内容。
  // 工具/技能开关已收敛到顶栏弹层(即点即存)——这里不再持有快照,否则保存会把
  // 打开抽屉时的旧 enabled_tools/技能集整个写回,覆盖弹层里刚做的改动。
  const inited = useRef(false)
  useEffect(() => {
    if (inited.current || !agent || !docsQ.isSuccess) return
    setForm({
      name: agent.name,
      model: agent.model,
      provider: agent.provider,
      thinking_level: agent.thinking_level ?? "",
      key_ref: agent.key_ref ?? "",
    })
    setInstructions(docs.find((d) => d.type === "AGENTS")?.content ?? "")
    inited.current = true
  }, [agent, docs, docsQ.isSuccess])

  const hadAgentsDoc = docs.some((d) => d.type === "AGENTS")
  const save = useMutation({
    mutationFn: async () => {
      await api.patchAgent(agentId, {
        ...form,
        key_ref: form.key_ref || null, // 空 = 用全局共享 Key
      })
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

  const invalid = !form.name || !form.model || !form.provider

  return (
    <div className="space-y-5">
      <SettingGroup label="基本">
        <SettingRow label="名称" block>
          <Input value={form.name} placeholder="名称" onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </SettingRow>
        <SettingRow label="模型" block>
          {/* 与 composer 同一选单;这里改的是本地草稿,点保存才落库(与其它字段一致) */}
          <ModelMenu value={form.model} onChange={(m) => setForm({ ...form, model: m })} />
        </SettingRow>
        <SettingRow label="Provider" block>
          <Input
            value={form.provider}
            placeholder="provider"
            onChange={(e) => setForm({ ...form, provider: e.target.value })}
          />
        </SettingRow>
      </SettingGroup>

      <SettingGroup label="模型行为">
        <SettingRow label="思考档位" block>
          <Segmented
            value={form.thinking_level}
            onChange={(v) => setForm({ ...form, thinking_level: v })}
            options={[
              { value: "", label: "默认" },
              { value: "low", label: "Low" },
              { value: "medium", label: "Medium" },
              { value: "high", label: "High" },
            ]}
          />
        </SettingRow>
        <SettingRow label="凭据" hint="空 = 用平台全局共享 Key" block>
          <SelectMenu
            value={form.key_ref}
            onChange={(v) => setForm({ ...form, key_ref: v })}
            options={[
              { value: "", label: "全局共享 Key" },
              ...creds.map((c) => ({ value: c.id, label: c.name, hint: c.masked })),
            ]}
          />
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
          disabled={save.isPending || invalid}
          title={invalid ? "名称/模型/provider 不能为空" : ""}
          onClick={() => save.mutate()}
        >
          {save.isPending ? "保存中…" : "保存"}
        </Button>
        {saved && <span className="text-xs font-medium text-brand-600">已保存 ✓</span>}
      </div>
    </div>
  )
}
