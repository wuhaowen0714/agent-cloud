import { useQueryClient } from "@tanstack/react-query"
import { api, HttpError } from "../../api/client"
import { useStore } from "../../store"
import type { AgentConfig, Message, Session } from "../../types"
import { type CompactResult, dedupeModels, type SlashContext, type StatusInfo } from "./commands"

// 把命令动作接到 store / api / react-query。读缓存的 key 与各处一致:
// agents/sessions 按 userId 命名,messages 按 sessionId。
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
  const openSettings = useStore((s) => s.openSettings)

  const agents = (): AgentConfig[] => qc.getQueryData<AgentConfig[]>(["agents", userId]) ?? []

  return {
    newSession: async () => {
      if (!agentId) return false
      const s = await api.createSession({ agent_config_id: agentId })
      await qc.invalidateQueries({ queryKey: ["sessions", userId] })
      setSession(s.id)
      return true
    },
    setModel: async (model) => {
      if (!agentId) return false
      await api.patchAgent(agentId, { model })
      await qc.invalidateQueries({ queryKey: ["agents", userId] })
      return true
    },
    compact: async (): Promise<CompactResult> => {
      if (!sessionId) return "error"
      try {
        const r = await api.compactSession(sessionId)
        return r.compacted ? "compacted" : "nothing"
      } catch (e) {
        return e instanceof HttpError && e.status === 409 ? "busy" : "error"
      }
    },
    modelSuggestions: () => dedupeModels(agents().map((a) => a.model)),
    status: (): StatusInfo => {
      const a = agents().find((x) => x.id === agentId) ?? null
      const sessions = qc.getQueryData<Session[]>(["sessions", userId]) ?? []
      const sess = sessions.find((x) => x.id === sessionId) ?? null
      const msgs = sessionId ? (qc.getQueryData<Message[]>(["messages", sessionId]) ?? []) : []
      return {
        agentName: a?.name ?? null,
        model: a?.model ?? null,
        provider: a?.provider ?? null,
        sessionTitle: sess?.title ?? null,
        sessionIdShort: sessionId ? sessionId.slice(0, 8) : null,
        messageCount: msgs.length,
        contextTokens: sess?.last_context_tokens ?? null,
      }
    },
    openSettings,
    notify: ui.notify,
    showStatus: ui.showStatus,
    showHelp: ui.showHelp,
  }
}
