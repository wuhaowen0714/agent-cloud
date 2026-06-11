import { useQueryClient } from "@tanstack/react-query"
import { api, HttpError } from "../../api/client"
import { useStore } from "../../store"
import type { AgentConfig, Message, Session } from "../../types"
import { useModelOptions } from "../model/useModelOptions"
import type { CompactResult, SlashContext, StatusInfo } from "./commands"

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
  const startCompaction = useStore((s) => s.startCompaction)
  const finishCompaction = useStore((s) => s.finishCompaction)
  const openSettings = useStore((s) => s.openSettings)
  const { options } = useModelOptions() // /model 建议与模型选单共用一个选项源

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
    compact: async (): Promise<void> => {
      // 捕获发起时的会话:压缩可能跨「用户切到别的会话」期间完成,结果必须写回发起的
      // 那个会话(running/result 都按 sid 存进 store),与「当前看哪个会话」彻底解耦,
      // 否则反馈会串到切过去的会话(原 bug)。
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
    modelSuggestions: () => options.map((o) => o.model),
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
