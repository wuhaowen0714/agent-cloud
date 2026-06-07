import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef } from "react"
import { api } from "../api/client"
import { streamTurn } from "../api/stream"
import { appendDelta, appendToolCall, attachToolResult } from "../blocks"
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
  // 在途回合的中断句柄 + 其所属会话;切会话/卸载时用来中断旧流。
  const inflight = useRef<{ abort: () => void; sessionId: string } | null>(null)

  // 切会话或卸载:中断在途的旧流。否则旧流的事件会继续写到新会话的 live 上(串台),
  // 且旧回合收尾会清掉/污染当前会话的状态。
  useEffect(() => {
    return () => {
      inflight.current?.abort()
      inflight.current = null
    }
  }, [sessionId])

  const { data: messages = [] } = useQuery({
    queryKey: ["messages", sessionId],
    queryFn: () => api.listMessages(sessionId!),
    enabled: !!sessionId,
  })

  if (!sessionId) {
    return <div className="flex flex-1 items-center justify-center text-slate-400">选择或新建一个会话开始聊天</div>
  }

  const onSend = async (text: string) => {
    // 已有进行中回合则忽略(防 IME 回车 / 双击 / disabled 更新前的竞态导致重复发送)。
    if (useStore.getState().live?.status === "streaming") return
    const sid = sessionId // 捕获本回合所属会话
    startLive(text)
    let errored = false
    const { done, abort } = streamTurn(sid, text, (e) => {
      // 仅当仍停留在该会话时才更新 live(丢弃已切走会话的残余事件)。
      if (useStore.getState().sessionId !== sid) return
      if (e.type === "thinking_delta") setLive((t) => ({ ...t, blocks: appendDelta(t.blocks, "thinking", e.text) }))
      else if (e.type === "text_delta") setLive((t) => ({ ...t, blocks: appendDelta(t.blocks, "text", e.text) }))
      else if (e.type === "tool_call_start")
        setLive((t) => ({ ...t, blocks: appendToolCall(t.blocks, { id: e.call_id, name: e.tool, arguments: e.args }) }))
      else if (e.type === "tool_result")
        setLive((t) => ({
          ...t,
          blocks: attachToolResult(t.blocks, e.call_id, { call_id: e.call_id, content: e.result, is_error: e.is_error }),
        }))
      else if (e.type === "turn_done") setLive((t) => ({ ...t, status: "done" }))
      else if (e.type === "error") { errored = true; setLive((t) => ({ ...t, status: "error", errorMessage: e.message })) }
    })
    inflight.current = { abort, sessionId: sid }
    try {
      await done
    } catch (err) {
      errored = true
      // 主动中断(切会话/卸载触发的 abort)不算失败,不写错误态。
      const aborted = err instanceof DOMException && err.name === "AbortError"
      if (!aborted && useStore.getState().sessionId === sid)
        setLive((t) => ({ ...t, status: "error", errorMessage: String(err) }))
    }
    if (inflight.current?.sessionId === sid) inflight.current = null
    // 拉该会话的权威历史(落库消息替代 live)。
    await qc.invalidateQueries({ queryKey: ["messages", sid] })
    // 成功且仍停留该会话时清掉 live(交回权威历史渲染);失败或已切走则不动。
    if (!errored && useStore.getState().sessionId === sid) clearLive()
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <MessageList messages={messages} />
      <Composer disabled={live?.status === "streaming"} onSend={onSend} />
    </div>
  )
}
