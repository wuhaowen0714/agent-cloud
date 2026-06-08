import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { BUILTIN_TOOLS, checkedToEnabled, enabledToChecked } from "../../agentConfig"
import { api } from "../../api/client"
import { useStore } from "../../store"
import { Button, Field, Input, Select, Textarea } from "../ui"

function SectionTitle({ children }: { children: string }) {
  return <div className="text-sm font-semibold text-slate-800">{children}</div>
}

export function AgentSettings() {
  const userId = useStore((s) => s.userId)!
  const agentId = useStore((s) => s.agentId)
  const setAgent = useStore((s) => s.setAgent)
  const qc = useQueryClient()

  // 新建模式:没有选中 agent
  const [draft, setDraft] = useState({ name: "", model: "", provider: "openai" })
  const createAgent = useMutation({
    mutationFn: () => api.createAgent({ ...draft }),
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["agents", userId] })
      setAgent(a.id)
    },
  })

  if (!agentId) {
    return (
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (draft.name && draft.model) createAgent.mutate()
        }}
      >
        <SectionTitle>新建 Agent</SectionTitle>
        {(["name", "model", "provider"] as const).map((k) => (
          <Input
            key={k}
            placeholder={k === "model" ? "model(如 DeepSeek-V4-Pro)" : k}
            value={draft[k]}
            onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
          />
        ))}
        <Button type="submit">创建</Button>
      </form>
    )
  }
  return <AgentEditor key={agentId} agentId={agentId} userId={userId} />
}

const toolRow = "flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-slate-50"

function AgentEditor({ agentId, userId }: { agentId: string; userId: string }) {
  const qc = useQueryClient()
  const agentsQ = useQuery({ queryKey: ["agents", userId], queryFn: () => api.listAgents() })
  const agent = (agentsQ.data ?? []).find((a) => a.id === agentId)
  const docsQ = useQuery({ queryKey: ["docs", "agent", agentId], queryFn: () => api.listDocs("agent", agentId) })
  const docs = docsQ.data ?? []
  const { data: pool = [] } = useQuery({ queryKey: ["skills", userId], queryFn: () => api.listSkills() })
  const { data: creds = [] } = useQuery({ queryKey: ["credentials", userId], queryFn: () => api.listCredentials() })
  const enabledQ = useQuery({ queryKey: ["agentSkills", agentId], queryFn: () => api.getAgentSkills(agentId) })

  const [form, setForm] = useState({ name: "", model: "", provider: "", thinking_level: "", key_ref: "" })
  const [tools, setTools] = useState<Set<string>>(new Set())
  const [instructions, setInstructions] = useState("")
  const [skillIds, setSkillIds] = useState<Set<string>>(new Set())
  const [saved, setSaved] = useState(false)

  // 仅在三组数据【首次加载完成】时灌一次本地草稿;之后的 refetch(如保存后失效)
  // 不再覆盖用户正在编辑的内容(避免清空指令"复活"/保存窗口内输入被冲掉)。
  const inited = useRef(false)
  useEffect(() => {
    if (inited.current || !agent || !docsQ.isSuccess || !enabledQ.isSuccess) return
    setForm({
      name: agent.name,
      model: agent.model,
      provider: agent.provider,
      thinking_level: agent.thinking_level ?? "",
      key_ref: agent.key_ref ?? "",
    })
    setTools(enabledToChecked(agent.enabled_tools))
    setInstructions(docs.find((d) => d.type === "AGENTS")?.content ?? "")
    setSkillIds(new Set((enabledQ.data ?? []).map((s) => s.id)))
    inited.current = true
  }, [agent, docs, docsQ.isSuccess, enabledQ.isSuccess, enabledQ.data])

  const hadAgentsDoc = docs.some((d) => d.type === "AGENTS")
  const save = useMutation({
    mutationFn: async () => {
      await api.patchAgent(agentId, {
        ...form,
        key_ref: form.key_ref || null, // 空 = 用全局共享 Key
        enabled_tools: checkedToEnabled(tools),
      })
      // 非空则写入;若原本有 AGENTS 文档则即使清空也写入(以持久化"清空"),否则不创建空文档。
      if (instructions.trim() || hadAgentsDoc) await api.putDoc("agent", "AGENTS", instructions, agentId)
      await api.setAgentSkills(agentId, [...skillIds])
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents", userId] })
      qc.invalidateQueries({ queryKey: ["agentSkills", agentId] })
      qc.invalidateQueries({ queryKey: ["docs", "agent", agentId] })
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    },
  })

  const toggle = (set: Set<string>, key: string) => {
    const n = new Set(set)
    if (n.has(key)) n.delete(key)
    else n.add(key)
    return n
  }
  const invalid = !form.name || !form.model || !form.provider

  return (
    <div className="space-y-5">
      <div className="space-y-3">
        <Field label="名称">
          <Input value={form.name} placeholder="名称" onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label="模型">
          <Input value={form.model} placeholder="模型" onChange={(e) => setForm({ ...form, model: e.target.value })} />
        </Field>
        <Field label="Provider">
          <Input value={form.provider} placeholder="provider" onChange={(e) => setForm({ ...form, provider: e.target.value })} />
        </Field>
        <Field label="思考档位">
          <Select value={form.thinking_level} onChange={(e) => setForm({ ...form, thinking_level: e.target.value })}>
            <option value="">默认</option>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
          </Select>
        </Field>
        <Field label="凭据" hint="空 = 用平台全局共享 Key">
          <Select value={form.key_ref} onChange={(e) => setForm({ ...form, key_ref: e.target.value })}>
            <option value="">全局共享 Key</option>
            {creds.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} · {c.masked}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      <div className="space-y-1">
        <SectionTitle>工具</SectionTitle>
        {BUILTIN_TOOLS.map((t) => (
          <label key={t.name} className={toolRow}>
            <input
              type="checkbox"
              className="h-4 w-4 accent-brand-600"
              checked={tools.has(t.name)}
              onChange={() => setTools((s) => toggle(s, t.name))}
            />
            <span className="font-mono text-xs text-slate-700">{t.name}</span>
            <span className="truncate text-xs text-slate-400">{t.desc}</span>
          </label>
        ))}
      </div>

      <div className="space-y-1.5">
        <SectionTitle>指令(AGENTS)</SectionTitle>
        <Textarea
          className="h-32 font-mono text-xs"
          placeholder="给这个 agent 的指令 / 人设(可选)"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
        />
      </div>

      <div className="space-y-1">
        <SectionTitle>启用技能</SectionTitle>
        {pool.length === 0 ? (
          <div className="px-2 text-xs text-slate-400">技能池为空 — 去"技能"页安装</div>
        ) : (
          pool.map((sk) => (
            <label key={sk.id} className={toolRow}>
              <input
                type="checkbox"
                className="h-4 w-4 accent-brand-600"
                checked={skillIds.has(sk.id)}
                onChange={() => setSkillIds((s) => toggle(s, sk.id))}
              />
              <span className="text-xs text-slate-700">{sk.name}</span>
              <span className="truncate text-xs text-slate-400">{sk.description}</span>
            </label>
          ))
        )}
      </div>

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
