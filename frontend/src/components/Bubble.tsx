import type { ReactNode } from "react"

// 用户气泡:右对齐、teal 实底、保留换行。
export function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-gradient-to-br from-brand-500 to-brand-600 px-3.5 py-2 text-sm text-white shadow-sm">
        {text}
      </div>
    </div>
  )
}

// 助手气泡:左对齐、白底描边,容纳一个回合的块流(思考/正文/工具)。
export function AssistantBubble({ children }: { children: ReactNode }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] rounded-2xl rounded-bl-md bg-white px-3.5 py-2.5 text-sm text-slate-800 shadow-card ring-1 ring-slate-200/70">
        {children}
      </div>
    </div>
  )
}
