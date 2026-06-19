import { useQuery, useQueryClient } from "@tanstack/react-query"

import { api, HttpError } from "../../api/client"
import { findProvider } from "../../models"
import { useStore } from "../../store"
import type { AgentConfig, Message, Session } from "../../types"
import { useProviderOptions } from "../model/useModelOptions"
import type { CompactResult, SlashContext, StatusInfo } from "./commands"

// 把命令动作接到 store / api / react-query。模型已下放到 session:/model 与 status 都按
// 当前会话工作。读缓存的 key 与各处一致:agents/sessions 按 userId,messages 按 sessionId。
export function useSlashCommands(ui: {
  notify: (msg: string) => void
  showStatus: () => void
  showHelp: () => void
}): SlashContext {
  const qc = useQueryClient()
  const userId = useStore((s) => s.userId)
  const sessionId = useStore((s) => s.sessionId)
  const agentId = useStore((s) => s.agentId)
  const setSession = useStore((s) => s.setSession)
  const startCompaction = useStore((s) => s.startCompaction)
  const finishCompaction = useStore((s) => s.finishCompaction)
  const openSettings = useStore((s) => s.openSettings)
  const setComposerDraft = useStore((s) => s.setComposerDraft)
  const { providers } = useProviderOptions() // /model 建议与图一选单共用 provider 选项源
  // 技能池:与 SkillsMenu / 设置页共用 ["skills", userId] 缓存,供 /skills 选用。
  const { data: skillPool = [] } = useQuery({
    queryKey: ["skills", userId],
    queryFn: () => api.listSkills(),
  })

  const sessions = (): Session[] => qc.getQueryData<Session[]>(["sessions", userId]) ?? []

  return {
    newSession: async () => {
      if (!agentId) return false
      const s = await api.createSession({ agent_config_id: agentId })
      await qc.invalidateQueries({ queryKey: ["sessions", userId] })
      setSession(s.id)
      return true
    },
    setModel: async (model) => {
      if (!sessionId) return false
      await api.patchSession(sessionId, { model }) // session 级:保持当前 provider/凭据
      await qc.invalidateQueries({ queryKey: ["sessions", userId] })
      return true
    },
    compact: async (): Promise<void> => {
      // 捕获发起时的会话:压缩可能跨「用户切到别的会话」期间完成,结果必须写回发起的
      // 那个会话(running/result 都按 sid 存进 store),与「当前看哪个会话」彻底解耦。
      const sid = sessionId
      if (!sid) return
      startCompaction(sid)
      let result: CompactResult
      try {
        const r = await api.compactSession(sid)
        result = r.compacted ? "compacted" : "nothing"
      } catch (e) {
        result = e instanceof HttpError && e.status === 409 ? "busy" : "error"
      }
      finishCompaction(sid, result)
    },
    modelSuggestions: () => providers.flatMap((p) => p.models),
    status: (): StatusInfo => {
      const agents = qc.getQueryData<AgentConfig[]>(["agents", userId]) ?? []
      const a = agents.find((x) => x.id === agentId) ?? null
      const sess = sessions().find((x) => x.id === sessionId) ?? null
      const msgs = sessionId ? (qc.getQueryData<Message[]>(["messages", sessionId]) ?? []) : []
      return {
        agentName: a?.name ?? null,
        model: sess?.model ?? null,
        provider: sess ? findProvider(providers, sess.credential_id).name : null,
        sessionTitle: sess?.title ?? null,
        sessionIdShort: sessionId ? sessionId.slice(0, 8) : null,
        messageCount: msgs.length,
        contextTokens: sess?.last_context_tokens ?? null,
      }
    },
    skillSuggestions: () => skillPool.map((s) => s.name),
    enableSkill: async (name) => {
      if (!agentId) return "noagent"
      const sk = skillPool.find((s) => s.name === name)
      if (!sk) return "notfound"
      const current = await api.getAgentSkills(agentId)
      if (current.some((s) => s.id === sk.id)) return "already"
      await api.setAgentSkills(agentId, [...current.map((s) => s.id), sk.id])
      await qc.invalidateQueries({ queryKey: ["agentSkills", agentId] })
      return "enabled"
    },
    setDraft: setComposerDraft,
    openSettings,
    notify: ui.notify,
    showStatus: ui.showStatus,
    showHelp: ui.showHelp,
  }
}
