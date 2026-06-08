import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef } from "react"
import { api } from "../api/client"
import { cancelTurn, resumeTurn, streamTurn } from "../api/stream"
import { appendDelta, appendToolCall, attachToolResult } from "../blocks"
import { useStore } from "../store"
import type { TurnEvent } from "../types"
import { Composer } from "./Composer"
import { MessageList } from "./MessageList"

export function ChatView() {
  const sessionId = useStore((s) => s.sessionId)
  const live = useStore((s) => s.live)
  const startLive = useStore((s) => s.startLive)
  const setLive = useStore((s) => s.setLive)
  const clearLive = useStore((s) => s.clearLive)
  const qc = useQueryClient()
  // 在途客户端连接(POST 或 GET resume)的中断句柄 + 所属会话
  const inflight = useRef<{ abort: () => void; sessionId: string } | null>(null)

  const { data: messages = [] } = useQuery({
    queryKey: ["messages", sessionId],
    queryFn: () => api.listMessages(sessionId!),
    enabled: !!sessionId,
  })

  // 把一个回合事件灌进 live(仅当仍停留在该会话,丢弃切走会话的残余事件)
  const feed = (sid: string, e: TurnEvent) => {
    if (useStore.getState().sessionId !== sid) return
    if (e.type === "thinking_delta")
      setLive((t) => ({ ...t, blocks: appendDelta(t.blocks, "thinking", e.text) }))
    else if (e.type === "text_delta")
      setLive((t) => ({ ...t, blocks: appendDelta(t.blocks, "text", e.text) }))
    else if (e.type === "tool_call_start")
      setLive((t) => ({
        ...t,
        blocks: appendToolCall(t.blocks, { id: e.call_id, name: e.tool, arguments: e.args }),
      }))
    else if (e.type === "tool_result")
      setLive((t) => ({
        ...t,
        blocks: attachToolResult(t.blocks, e.call_id, {
          call_id: e.call_id,
          content: e.result,
          is_error: e.is_error,
        }),
      }))
    else if (e.type === "turn_done") setLive((t) => ({ ...t, status: "done" }))
    else if (e.type === "reset")
      // 透明自动重试:清掉本回合已显示内容,从头重来(状态保持 streaming)
      setLive((t) => ({ ...t, blocks: [], status: "streaming", errorMessage: undefined }))
    else if (e.type === "error")
      setLive((t) => ({
        ...t,
        status: "error",
        errorMessage: e.message,
        recoverable: e.recoverable,
      }))
  }

  // 消费一个流(POST 或 GET resume)到结束:成功→刷新历史+清 live;主动中断(切走)→不动。
  const consume = async (sid: string, handle: { done: Promise<void>; abort: () => void }) => {
    inflight.current = { abort: handle.abort, sessionId: sid }
    try {
      await handle.done
    } catch (err) {
      const aborted = err instanceof DOMException && err.name === "AbortError"
      // 切走/卸载导致的中断:服务端回合仍在跑,切回再 resume,这里不收尾。
      if (aborted) return
      if (useStore.getState().sessionId === sid)
        setLive((t) => ({ ...t, status: "error", errorMessage: String(err) }))
    }
    if (inflight.current?.sessionId === sid) inflight.current = null
    const errored = useStore.getState().live?.status === "error"
    await qc.invalidateQueries({ queryKey: ["messages", sid] })
    if (!errored && useStore.getState().sessionId === sid) clearLive()
  }

  // 切会话/卸载:中断【客户端连接】(服务端回合继续);不再 cancel。
  useEffect(() => {
    return () => {
      inflight.current?.abort()
      inflight.current = null
    }
  }, [sessionId])

  // 打开会话/刷新后:若该会话有进行中回合、且当前没有本会话的 live,挂上去续看(补播+实时)。
  useEffect(() => {
    const sid = sessionId
    if (!sid) return
    if (useStore.getState().live?.sessionId === sid) return // 刚 POST 起的,别重复挂
    let cancelledLocal = false
    let abortFn: (() => void) | null = null
    void (async () => {
      const handle = await resumeTurn(sid, (e) => feed(sid, e))
      if (!handle) return // 204:没有在跑的回合
      if (cancelledLocal || useStore.getState().sessionId !== sid) {
        handle.abort()
        return
      }
      abortFn = handle.abort
      startLive("", sid) // user 消息由已落库 messages 渲染;live 只放助手 blocks
      await consume(sid, handle)
    })()
    return () => {
      cancelledLocal = true
      abortFn?.()
    }
  }, [sessionId])

  if (!sessionId) {
    return (
      <div className="flex flex-1 items-center justify-center text-slate-400">
        选择或新建一个会话开始聊天
      </div>
    )
  }

  const onSend = async (text: string) => {
    // 已有进行中回合则忽略(防 IME 回车 / 双击 / disabled 更新前的竞态导致重复发送)。
    if (useStore.getState().live?.status === "streaming") return
    const sid = sessionId
    startLive(text, sid)
    await consume(sid, streamTurn(sid, text, (e) => feed(sid, e)))
  }

  const onStop = () => {
    if (sessionId) void cancelTurn(sessionId)
  }

  // 手动重试:重发本回合的用户消息(瞬时错误自动重试耗尽后给用户的兜底入口)。
  const onRetry = () => {
    const t = useStore.getState().live
    if (t && t.status === "error") void onSend(t.userText)
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <MessageList messages={messages} onRetry={onRetry} />
      <Composer disabled={live?.status === "streaming"} onSend={onSend} onStop={onStop} />
    </div>
  )
}
