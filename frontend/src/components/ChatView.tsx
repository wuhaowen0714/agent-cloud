import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef } from "react"
import { api, HttpError } from "../api/client"
import { pollSessionTitle } from "../api/queryClient"
import { cancelTurn, resumeTurn, streamTurn } from "../api/stream"
import {
  appendToSubagent,
  applyEvent,
  dropPendingTools,
  finishSubagent,
  startSubagent,
} from "../blocks"
import { useStore } from "../store"
import type { TurnEvent } from "../types"
import { Composer } from "./Composer"
import { MessageList } from "./MessageList"

export function ChatView() {
  const sessionId = useStore((s) => s.sessionId)
  const userId = useStore((s) => s.userId)
  const live = useStore((s) => s.live)
  const startLive = useStore((s) => s.startLive)
  const setLive = useStore((s) => s.setLive)
  const clearLive = useStore((s) => s.clearLive)
  const setSession = useStore((s) => s.setSession)
  const setComposerDraft = useStore((s) => s.setComposerDraft)
  const qc = useQueryClient()
  // 在途客户端连接(POST 或 GET resume)的中断句柄 + 所属会话
  const inflight = useRef<{ abort: () => void; sessionId: string } | null>(null)
  // 回滚/fork 在途互斥:防双击发两次请求(输者撞 422 弹假错误,且可能交错出竞态)。
  const actionBusy = useRef(false)

  const messagesQ = useQuery({
    queryKey: ["messages", sessionId],
    queryFn: () => api.listMessages(sessionId!),
    enabled: !!sessionId,
  })
  const messages = messagesQ.data ?? []

  // 选中的会话已被删 / 不属于当前用户(后端 404)→ 丢弃这个悬空选择,回到空态,
  // 避免对着一个不存在的会话渲染聊天面板、甚至向其 POST 回合(如换用户后 localStorage 残留的会话)。
  // 同时失效 sessions 缓存:否则 Sidebar 自动落位会从陈旧列表再次选中这条已删会话,
  // 形成「404 → 清空 → 又选中 → 404」的无界循环(典型:另一标签页删掉了本页选中的会话)。
  useEffect(() => {
    const err = messagesQ.error as { status?: number } | null
    if (err?.status === 404) {
      useStore.getState().setSession(null)
      void qc.invalidateQueries({ queryKey: ["sessions"] })
    }
  }, [messagesQ.error, qc])

  // 把一个回合事件灌进 live(仅当仍停留在该会话,丢弃切走会话的残余事件)
  const feed = (sid: string, e: TurnEvent) => {
    if (useStore.getState().sessionId !== sid) return
    if (e.type === "subagent_started")
      setLive((t) => ({
        ...t,
        blocks: startSubagent(t.blocks, e.subagent_id, e.description, e.prompt),
      }))
    else if (e.type === "subagent_done")
      setLive((t) => ({ ...t, blocks: finishSubagent(t.blocks, e.subagent_id, e.ok) }))
    else if ("subagent_id" in e && e.subagent_id)
      // 子 agent 事件:路由进对应 subagent 块的内部 blocks(而非顶层) → 折叠卡片
      setLive((t) => ({ ...t, blocks: appendToSubagent(t.blocks, e.subagent_id as string, e) }))
    else if (e.type === "turn_done") setLive((t) => ({ ...t, status: "done" }))
    else if (e.type === "reset")
      // 透明自动重试:清掉本回合已显示内容,从头重来(状态保持 streaming)
      setLive((t) => ({
        ...t,
        blocks: [],
        status: "streaming",
        errorMessage: undefined,
        recoverable: undefined,
      }))
    else if (e.type === "error")
      // 终态:剥掉 pending 进度卡(流已死,永远等不到升级),半截文本照旧保留
      setLive((t) => ({
        ...t,
        blocks: dropPendingTools(t.blocks),
        status: "error",
        errorMessage: e.message,
        recoverable: e.recoverable,
      }))
    else
      // 顶层(主 agent)的 thinking/text/tool 增量
      setLive((t) => ({ ...t, blocks: applyEvent(t.blocks, e) }))
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
        setLive((t) => ({
          ...t,
          blocks: dropPendingTools(t.blocks),
          status: "error",
          errorMessage: String(err),
        }))
    }
    if (inflight.current?.sessionId === sid) inflight.current = null
    const errored = useStore.getState().live?.status === "error"
    // 成功收尾才刷历史:出错/取消时用户消息已乐观显示在 live、助手部分未落库,此时刷 messages 只会把
    // 已落库的【同一条用户消息】拉回来,与 live.userText 重复渲染成两条提问(仍由 live 负责显示该回合)。
    if (!errored) await qc.invalidateQueries({ queryKey: ["messages", sid] })
    // 本回合 agent 可能调了 notify(后端保证在 turn_done 前落库)→ 立即失效通知查询,
    // 当前会话里就能马上弹 toast,不必等 15s 轮询或手动刷新。
    if (!errored) await qc.invalidateQueries({ queryKey: ["notifications"] })
    await qc.invalidateQueries({ queryKey: ["sessions"] }) // 刷 last_context_tokens(/status 用),出错也刷
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
      let handle: Awaited<ReturnType<typeof resumeTurn>>
      try {
        handle = await resumeTurn(sid, (e) => feed(sid, e))
      } catch {
        return // 会话不存在/无权(404)等:交给 messages 查询的 404 处理来清理选择
      }
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

  const onSend = async (text: string, images: string[] = []) => {
    // 已有进行中回合则忽略(防 IME 回车 / 双击 / disabled 更新前的竞态导致重复发送)。
    if (useStore.getState().live?.status === "streaming") return
    const sid = sessionId
    // 该会话正在压缩(与回合同锁)→ 发出去必撞 409。拦在这里也覆盖来自错误气泡「重试」的
    // 路径(重试不经 Composer 的 busy 禁用,直接调 onSend)。
    if (useStore.getState().compactions[sid]?.phase === "running") return
    const wasFirst = messages.length === 0 // 首回合:标题将在服务端异步生成
    startLive(text, sid)
    // 重试(onRetry)走 images=[]:错误兜底重发不重带图(活跃图片仍由后端从历史回灌)。
    await consume(sid, streamTurn(sid, text, (e) => feed(sid, e), images))
    // 首回合标题在服务端异步生成:轮询刷 sessions 直到它出现(单次延迟刷常赶不上 LLM)
    if (wasFirst && userId) pollSessionTitle(qc, userId, sid)
  }

  const onStop = () => {
    if (sessionId) void cancelTurn(sessionId)
  }

  // 手动重试:重发本回合的用户消息(瞬时错误自动重试耗尽后给用户的兜底入口)。
  const onRetry = () => {
    const t = useStore.getState().live
    if (t && t.status === "error") void onSend(t.userText)
  }

  // 回滚:删该用户消息及其之后,把它的文本回填输入框。与回合同锁,在跑 → 409 提示。
  const onRollback = async (messageId: string) => {
    if (actionBusy.current) return
    const sid = sessionId // 捕获发起会话:resolve 时若已切走,数据照刷但 UI 副作用不泼到别的会话
    actionBusy.current = true
    try {
      const r = await api.rollbackSession(sid, messageId)
      await qc.invalidateQueries({ queryKey: ["messages", sid] })
      await qc.invalidateQueries({ queryKey: ["sessions"] })
      if (useStore.getState().sessionId === sid) {
        clearLive() // 可能删掉了正在错误展示的 live 回合
        setComposerDraft(r.user_text)
      }
    } catch (e) {
      if (e instanceof HttpError && e.status === 409) window.alert("会话正忙,请稍候再试")
      else window.alert("回滚失败,请稍后再试")
    } finally {
      actionBusy.current = false
    }
  }

  // Fork:复制该用户消息「之前」的历史到新会话,切过去并回填(原会话不动)。
  const onFork = async (messageId: string) => {
    if (actionBusy.current) return
    const sid = sessionId
    actionBusy.current = true
    try {
      const r = await api.forkSession(sid, messageId)
      await qc.invalidateQueries({ queryKey: ["sessions"] })
      // 已切走则不强行把用户拽到新分支(分支已建好、在会话列表里)
      if (useStore.getState().sessionId === sid) {
        setSession(r.new_session_id) // 切到新会话(setSession 会清 live)
        setComposerDraft(r.user_text)
      }
    } catch {
      window.alert("Fork 失败,请稍后再试")
    } finally {
      actionBusy.current = false
    }
  }

  return (
    // min-h-0:flex 子项默认 min-height:auto(=内容高),会把整列撑过视口、让整页滚动;
    // 收掉它,滚动才发生在 MessageList 的 overflow-auto 里(侧栏/composer 钉在视口内)。
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      {/* key=会话:切会话整组件重建,跟随状态/滚动位置回到初值(粘底) */}
      <MessageList
        key={sessionId}
        messages={messages}
        onRetry={onRetry}
        onRollback={onRollback}
        onFork={onFork}
      />
      <Composer disabled={live?.status === "streaming"} onSend={onSend} onStop={onStop} />
    </div>
  )
}
