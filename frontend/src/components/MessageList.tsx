import { useEffect, useRef } from "react"
import { useStore } from "../store"
import type { Message } from "../types"
import { Markdown } from "./Markdown"
import { MessageBubble } from "./MessageBubble"
import { ThinkingPanel } from "./ThinkingPanel"
import { ToolCallCard } from "./ToolCallCard"

export function MessageList({ messages }: { messages: Message[] }) {
  const live = useStore((s) => s.live)
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, live])

  return (
    <div className="flex-1 space-y-3 overflow-auto p-4">
      {messages.map((m) => (
        <MessageBubble key={m.id} message={m} />
      ))}
      {live && (
        <>
          {/* 乐观渲染本回合的用户消息(权威历史在 turn_done 后接管) */}
          {live.userText && (
            <div className="flex justify-end">
              <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl bg-brand-600 px-3 py-2 text-sm text-white">
                {live.userText}
              </div>
            </div>
          )}
          <div className="flex justify-start">
            <div className="max-w-[80%] rounded-2xl bg-white px-3 py-2 text-sm text-slate-800 shadow-sm ring-1 ring-slate-200">
              <ThinkingPanel text={live.thinking} defaultOpen />
              {live.toolCalls.map((tc) => (
                <ToolCallCard key={tc.call.id} call={tc.call} result={tc.result} />
              ))}
              {live.text && <Markdown>{live.text}</Markdown>}
              {live.status === "streaming" && (
                <span className="ml-0.5 animate-pulse text-brand-600">▍</span>
              )}
              {live.status === "error" && (
                <div className="mt-1 text-xs text-red-600">
                  ⚠ {live.errorMessage ?? "回合失败"},可重试。
                </div>
              )}
            </div>
          </div>
        </>
      )}
      <div ref={endRef} />
    </div>
  )
}
