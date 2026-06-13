import type { ReactNode } from "react"
import { parseUserMessage } from "../chatText"
import { UserAttachments } from "./UserAttachments"

// 用户气泡:右对齐、teal 实底、保留换行。带附件时,缩略图/文件 chip 在气泡上方展示,正文
// 只留用户真正打的字(parseUserMessage 摘掉 Composer 追加给 agent 的内部提示 + 裸路径)。
export function UserBubble({ text }: { text: string }) {
  const { body, attachments } = parseUserMessage(text)
  return (
    <div className="flex flex-col items-end gap-1.5">
      {attachments.length > 0 && <UserAttachments paths={attachments} />}
      {body && (
        <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-gradient-to-br from-brand-500 to-brand-600 px-3.5 py-2 text-sm text-white shadow-sm">
          {body}
        </div>
      )}
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
