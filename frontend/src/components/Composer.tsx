import { useState } from "react"

export function Composer({ disabled, onSend }: { disabled: boolean; onSend: (text: string) => void }) {
  const [text, setText] = useState("")
  const send = () => {
    const t = text.trim()
    if (!t || disabled) return
    onSend(t)
    setText("")
  }
  return (
    <div className="flex gap-2 border-t border-slate-200 bg-white p-3">
      <textarea
        className="min-h-[44px] flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
        placeholder={disabled ? "生成中…" : "说点什么(Enter 发送,Shift+Enter 换行)"}
        rows={1}
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send() }
        }}
      />
      <button
        className="rounded-lg bg-brand-600 px-4 text-sm text-white enabled:hover:bg-brand-700 disabled:opacity-40"
        disabled={disabled}
        onClick={send}
      >
        发送
      </button>
    </div>
  )
}
