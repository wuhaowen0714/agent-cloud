import { useQuery } from "@tanstack/react-query"
import { ChevronDown } from "lucide-react"
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react"
import { api } from "../api/client"
import { messagesToTurns } from "../blocks"
import { parseUserMessage } from "../chatText"
import { isNearBottom } from "../scroll"
import { useStore } from "../store"
import { fmtTime } from "../time"
import type { Message } from "../types"
import { AssistantBubble, UserBubble } from "./Bubble"
import { MessageActions } from "./MessageActions"
import { resolveWorkspacePath } from "../workspacePaths"
import { TurnBlocks } from "./TurnBlocks"

export function MessageList({
  messages,
  onRetry,
  onRollback,
  onFork,
}: {
  messages: Message[]
  onRetry?: () => void
  onRollback?: (messageId: string) => void
  onFork?: (messageId: string) => void
}) {
  const live = useStore((s) => s.live)
  // 正文里的工作区路径 → 可点链接:文件索引与 @ 引用共用 query(30s stale);索引未就绪时
  // resolve 恒 null(普通 code),渐进增强。点击 → 文件抽屉定位/预览。
  const userId = useStore((s) => s.userId)
  const openFileDrawerAt = useStore((s) => s.openFileDrawerAt)
  const { data: fileIndex = [] } = useQuery({
    queryKey: ["fileIndex", userId],
    queryFn: () => api.indexFiles(),
    enabled: !!userId,
    staleTime: 30_000,
  })
  const resolvePath = useCallback(
    (text: string) => resolveWorkspacePath(text, fileIndex),
    [fileIndex],
  )
  // 当前会话正在压缩 → 藏掉「重试」:重试会触发回合,而压缩与回合同锁,必撞 409(onSend 也兜底拦)。
  const compacting = useStore((s) => !!s.sessionId && s.compactions[s.sessionId]?.phase === "running")
  const endRef = useRef<HTMLDivElement>(null)
  // 粘底跟随:在底部才自动滚,上翻即停(spec 2026-06-11-scroll-follow)。
  // followRef 是权威值(effect 读,不触发渲染);following state 只驱动浮钮显隐。
  const followRef = useRef(true)
  const [following, setFollowing] = useState(true)
  const lastTopRef = useRef(0)
  const prevLiveRef = useRef(live)

  const setFollow = (v: boolean) => {
    followRef.current = v
    setFollowing((prev) => (prev === v ? prev : v)) // 边界翻转才真 setState(滚动事件高频)
  }

  const onScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget
    const near = isNearBottom(el)
    const scrolledUp = el.scrollTop < lastTopRef.current
    lastTopRef.current = el.scrollTop
    // 关跟随的唯一信号:scrollTop 实际下降(用户上翻)且不在底。scroll 事件是异步派发的,
    // 程序滚动 + 下一个 delta 撑高内容后才到的事件会读到「距底变大但 scrollTop 没降」——
    // 那不是用户行为,不能熄火(审查 H1:否则流式中跟随会自发停止)。
    if (scrolledUp && !near) setFollow(false)
    else if (near) setFollow(true)
  }

  // 用户发送新回合(startLive 必刷新 startedAt;delta 的 setLive 不动它):强制恢复跟随。
  // 用 startedAt 而非 null→非空 判定——错误回合的 live 不被清,直接再发是非空→非空(审查 M1)。
  // resume 续看(startLive("")):userText 为空,不触发。
  useEffect(() => {
    const prev = prevLiveRef.current
    prevLiveRef.current = live
    if (live?.userText && live.startedAt !== prev?.startedAt) {
      setFollow(true)
      endRef.current?.scrollIntoView()
    }
  }, [live])

  useEffect(() => {
    // 即时滚动(非 smooth):平滑动画在高频 delta 下排队,正是「拽走」感的帮凶
    if (followRef.current) endRef.current?.scrollIntoView()
  }, [messages, live])

  const scrollToBottom = () => {
    setFollow(true)
    endRef.current?.scrollIntoView()
  }

  // 已落库历史:按回合分组,每个回合 = 一个用户气泡 + 一个助手气泡(块流)。
  // memo:MessageList 订阅 live,流式期间每帧重渲染,避免每帧重算整段历史。
  const turns = useMemo(() => messagesToTurns(messages), [messages])

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      {!following && (
        <button
          type="button"
          aria-label="回到底部"
          onClick={scrollToBottom}
          className="absolute bottom-4 right-6 z-10 flex h-9 w-9 items-center justify-center rounded-full bg-white text-slate-500 shadow-pop ring-1 ring-slate-200 transition hover:text-slate-800"
        >
          <ChevronDown size={18} />
        </button>
      )}
      <div data-scroll-container onScroll={onScroll} className="flex-1 overflow-auto p-4">
      <div className="mx-auto max-w-5xl space-y-4">
        {turns.map((turn, i) => {
        // user 消息但没有任何助手块 = 该回合被取消/出错(未完成)。但最后一条且当前
        // 有 live(正在流式/重连)的不算——那是进行中的回合,助手内容在下面的 live 里。
        const unfinished =
          turn.userText !== null && turn.blocks.length === 0 && !(i === turns.length - 1 && live)
        return (
          <Fragment key={turn.id}>
            {/* 气泡 + 时间行包成组:父级 space-y-4 作用于组,时间行紧贴自己的气泡 */}
            {turn.userText !== null && (
              <div className="group space-y-1">
                <UserBubble text={turn.userText} />
                {/* 操作 + 时间同行(hover 显操作,时间常驻),避免额外占位行 */}
                <div className="flex items-center justify-end gap-2 pr-1">
                  <MessageActions
                    text={parseUserMessage(turn.userText).body}
                    onRollback={onRollback ? () => onRollback(turn.id) : undefined}
                    onFork={onFork ? () => onFork(turn.id) : undefined}
                  />
                  {turn.userAt && (
                    <span className="text-[11px] text-slate-400">{fmtTime(turn.userAt)}</span>
                  )}
                </div>
              </div>
            )}
            {turn.blocks.length > 0 && (
              <div className="group space-y-1">
                <AssistantBubble>
                  <TurnBlocks
                    blocks={turn.blocks}
                    resolvePath={resolvePath}
                    onOpenPath={openFileDrawerAt}
                  />
                </AssistantBubble>
                <div className="flex items-center gap-2 pl-1">
                  {turn.doneAt && (
                    <span className="text-[11px] text-slate-400">{fmtTime(turn.doneAt)}</span>
                  )}
                  <MessageActions
                    text={turn.blocks.flatMap((b) => (b.kind === "text" ? [b.text] : [])).join("\n")}
                  />
                </div>
              </div>
            )}
            {unfinished && (
              <div className="text-center text-xs text-slate-400">— 回合未完成 —</div>
            )}
          </Fragment>
        )
      })}
      {live && (
        <>
          {/* 乐观渲染本回合的用户消息(权威历史在 turn_done 后接管);助手流式中不显示时间 */}
          {live.userText && (
            <div className="space-y-1">
              <UserBubble text={live.userText} />
              {live.startedAt && (
                <div className="flex justify-end pr-1 text-[11px] text-slate-400">{fmtTime(live.startedAt)}</div>
              )}
            </div>
          )}
          <AssistantBubble>
            <TurnBlocks
              blocks={live.blocks}
              streaming={live.status === "streaming"}
              resolvePath={resolvePath}
              onOpenPath={openFileDrawerAt}
            />
            {live.status === "error" && (
              <div className="mt-1 text-xs text-red-600">
                {live.recoverable === false ? (
                  // 不可恢复(如上下文过大):不给重试,引导开新会话
                  <span>⚠ {live.errorMessage ?? "回合失败"} —— 请开新会话。</span>
                ) : (
                  <span>
                    ⚠ {live.errorMessage ?? "回合失败"}
                    {onRetry && !compacting && (
                      <button
                        type="button"
                        onClick={onRetry}
                        className="ml-2 underline hover:text-red-800"
                      >
                        重试
                      </button>
                    )}
                  </span>
                )}
              </div>
            )}
          </AssistantBubble>
        </>
      )}
        <div ref={endRef} />
        </div>
      </div>
    </div>
  )
}
