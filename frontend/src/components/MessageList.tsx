import { Fragment, useEffect, useMemo, useRef } from "react"
import { messagesToTurns } from "../blocks"
import { useStore } from "../store"
import { fmtTime } from "../time"
import type { Message } from "../types"
import { AssistantBubble, UserBubble } from "./Bubble"
import { TurnBlocks } from "./TurnBlocks"

export function MessageList({
  messages,
  onRetry,
}: {
  messages: Message[]
  onRetry?: () => void
}) {
  const live = useStore((s) => s.live)
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, live])

  // 已落库历史:按回合分组,每个回合 = 一个用户气泡 + 一个助手气泡(块流)。
  // memo:MessageList 订阅 live,流式期间每帧重渲染,避免每帧重算整段历史。
  const turns = useMemo(() => messagesToTurns(messages), [messages])

  return (
    <div className="flex-1 overflow-auto p-4">
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
              <div className="space-y-1">
                <UserBubble text={turn.userText} />
                {turn.userAt && (
                  <div className="flex justify-end pr-1 text-[11px] text-slate-400">{fmtTime(turn.userAt)}</div>
                )}
              </div>
            )}
            {turn.blocks.length > 0 && (
              <div className="space-y-1">
                <AssistantBubble>
                  <TurnBlocks blocks={turn.blocks} />
                </AssistantBubble>
                {turn.doneAt && (
                  <div className="pl-1 text-[11px] text-slate-400">{fmtTime(turn.doneAt)}</div>
                )}
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
            <TurnBlocks blocks={live.blocks} streaming={live.status === "streaming"} />
            {live.status === "error" && (
              <div className="mt-1 text-xs text-red-600">
                {live.recoverable === false ? (
                  // 不可恢复(如上下文过大):不给重试,引导开新会话
                  <span>⚠ {live.errorMessage ?? "回合失败"} —— 请开新会话。</span>
                ) : (
                  <span>
                    ⚠ {live.errorMessage ?? "回合失败"}
                    {onRetry && (
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
  )
}
