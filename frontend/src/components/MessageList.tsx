import { Fragment, useEffect, useMemo, useRef } from "react"
import { messagesToTurns } from "../blocks"
import { useStore } from "../store"
import type { Message } from "../types"
import { AssistantBubble, UserBubble } from "./Bubble"
import { TurnBlocks } from "./TurnBlocks"

export function MessageList({ messages }: { messages: Message[] }) {
  const live = useStore((s) => s.live)
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, live])

  // 已落库历史:按回合分组,每个回合 = 一个用户气泡 + 一个助手气泡(块流)。
  // memo:MessageList 订阅 live,流式期间每帧重渲染,避免每帧重算整段历史。
  const turns = useMemo(() => messagesToTurns(messages), [messages])

  return (
    <div className="flex-1 space-y-3 overflow-auto p-4">
      {turns.map((turn, i) => {
        // user 消息但没有任何助手块 = 该回合被取消/出错(未完成)。但最后一条且当前
        // 有 live(正在流式/重连)的不算——那是进行中的回合,助手内容在下面的 live 里。
        const unfinished =
          turn.userText !== null && turn.blocks.length === 0 && !(i === turns.length - 1 && live)
        return (
          <Fragment key={turn.id}>
            {turn.userText !== null && <UserBubble text={turn.userText} />}
            {turn.blocks.length > 0 && (
              <AssistantBubble>
                <TurnBlocks blocks={turn.blocks} />
              </AssistantBubble>
            )}
            {unfinished && (
              <div className="text-center text-xs text-slate-400">— 回合未完成 —</div>
            )}
          </Fragment>
        )
      })}
      {live && (
        <>
          {/* 乐观渲染本回合的用户消息(权威历史在 turn_done 后接管) */}
          {live.userText && <UserBubble text={live.userText} />}
          <AssistantBubble>
            <TurnBlocks blocks={live.blocks} streaming={live.status === "streaming"} />
            {live.status === "error" && (
              <div className="mt-1 text-xs text-red-600">⚠ {live.errorMessage ?? "回合失败"},可重试。</div>
            )}
          </AssistantBubble>
        </>
      )}
      <div ref={endRef} />
    </div>
  )
}
