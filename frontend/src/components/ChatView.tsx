import { useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "../api/client"
import { streamTurn } from "../api/stream"
import { useStore } from "../store"
import { Composer } from "./Composer"
import { MessageList } from "./MessageList"

export function ChatView() {
  const sessionId = useStore((s) => s.sessionId)
  const live = useStore((s) => s.live)
  const startLive = useStore((s) => s.startLive)
  const setLive = useStore((s) => s.setLive)
  const clearLive = useStore((s) => s.clearLive)
  const qc = useQueryClient()

  const { data: messages = [] } = useQuery({
    queryKey: ["messages", sessionId],
    queryFn: () => api.listMessages(sessionId!),
    enabled: !!sessionId,
  })

  if (!sessionId) {
    return <div className="flex flex-1 items-center justify-center text-slate-400">选择或新建一个会话开始聊天</div>
  }

  const onSend = async (text: string) => {
    startLive()
    let errored = false
    const { done } = streamTurn(sessionId, text, (e) => {
      if (e.type === "thinking_delta") setLive((t) => ({ ...t, thinking: t.thinking + e.text }))
      else if (e.type === "text_delta") setLive((t) => ({ ...t, text: t.text + e.text }))
      else if (e.type === "tool_call_start")
        setLive((t) => ({ ...t, toolCalls: [...t.toolCalls, { call: { id: e.call_id, name: e.tool, arguments: e.args } }] }))
      else if (e.type === "tool_result")
        setLive((t) => ({
          ...t,
          toolCalls: t.toolCalls.map((tc) =>
            tc.call.id === e.call_id ? { ...tc, result: { call_id: e.call_id, content: e.result, is_error: e.is_error } } : tc,
          ),
        }))
      else if (e.type === "turn_done") setLive((t) => ({ ...t, status: "done" }))
      else if (e.type === "error") { errored = true; setLive((t) => ({ ...t, status: "error", errorMessage: e.message })) }
    })
    try {
      await done
    } catch (err) {
      errored = true
      setLive((t) => ({ ...t, status: "error", errorMessage: String(err) }))
    }
    // 拉权威历史;成功则清掉 live(由落库消息替代),失败则保留错误态
    await qc.invalidateQueries({ queryKey: ["messages", sessionId] })
    if (!errored) clearLive()
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <MessageList messages={messages} />
      <Composer disabled={live?.status === "streaming"} onSend={onSend} />
    </div>
  )
}
