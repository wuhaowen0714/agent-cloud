import type { Message } from "../types"
import { ToolCallCard } from "./ToolCallCard"

export function MessageBubble({ message }: { message: Message }) {
  const { role, content } = message
  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl bg-brand-600 px-3 py-2 text-sm text-white">
          {content.text}
        </div>
      </div>
    )
  }
  if (role === "tool") {
    return (
      <div className="flex justify-start">
        <div className="max-w-[80%]">
          {content.tool_results.map((r) => (
            <ToolCallCard key={r.call_id} call={{ id: r.call_id, name: "result", arguments: {} }} result={r} />
          ))}
        </div>
      </div>
    )
  }
  // assistant
  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] rounded-2xl bg-white px-3 py-2 text-sm text-slate-800 shadow-sm ring-1 ring-slate-200">
        {content.text && <div className="whitespace-pre-wrap">{content.text}</div>}
        {content.tool_calls.map((c) => (
          <ToolCallCard key={c.id} call={c} />
        ))}
      </div>
    </div>
  )
}
