import { useState } from "react"
import { Button, Textarea } from "./ui"

export function Composer({
  disabled,
  onSend,
  onStop,
}: {
  disabled: boolean
  onSend: (text: string) => void
  onStop?: () => void
}) {
  const [text, setText] = useState("")
  const send = () => {
    const t = text.trim()
    if (!t || disabled) return
    onSend(t)
    setText("")
  }
  return (
    <div className="border-t border-slate-200 bg-white/80 p-3 backdrop-blur">
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <Textarea
          className="min-h-[44px] flex-1"
          placeholder={disabled ? "生成中…" : "说点什么(Enter 发送,Shift+Enter 换行)"}
          rows={1}
          value={text}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
        />
        {disabled && onStop ? (
          <Button variant="secondary" className="h-11" onClick={onStop}>
            停止
          </Button>
        ) : (
          <Button className="h-11" disabled={disabled} onClick={send}>
            发送
          </Button>
        )}
      </div>
    </div>
  )
}
