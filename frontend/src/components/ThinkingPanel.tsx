import { useState } from "react"

export function ThinkingPanel({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  if (!text) return null
  return (
    <div className="mt-1 text-xs">
      <button className="text-slate-400 hover:text-slate-600" onClick={() => setOpen((v) => !v)}>
        {open ? "▾ 思考" : "▸ 思考"}
      </button>
      {open && (
        <pre className="mt-1 whitespace-pre-wrap rounded bg-slate-50 p-2 font-mono text-slate-500">
          {text}
        </pre>
      )}
    </div>
  )
}
