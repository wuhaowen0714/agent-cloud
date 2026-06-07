import { useState } from "react"
import type { ToolCall, ToolResult } from "../types"

// 把工具调用浓缩成「主摘要 + 可选细节」:bash→命令、write/read_file→文件名,其余→紧凑 JSON。
// 大参数(如 write_file 的 content)放进可折叠的细节区,不污染头部摘要。
function describe(call: ToolCall): { summary: string; details: string | null } {
  const a = (call.arguments ?? {}) as Record<string, unknown>
  if (call.name === "bash") return { summary: String(a.command ?? ""), details: null }
  if (call.name === "write_file") {
    const content = typeof a.content === "string" ? a.content : ""
    return { summary: String(a.path ?? ""), details: content || null }
  }
  if (call.name === "read_file") return { summary: String(a.path ?? ""), details: null }
  const keys = Object.keys(a)
  return { summary: keys.length ? JSON.stringify(a) : "", details: keys.length ? JSON.stringify(a, null, 2) : null }
}

export function ToolCallCard({ call, result }: { call: ToolCall; result?: ToolResult }) {
  const [open, setOpen] = useState(false)
  const { summary, details } = describe(call)
  const error = result?.is_error ?? false

  return (
    <div className="my-1.5 overflow-hidden rounded-lg border border-l-2 border-slate-200 border-l-brand-200 bg-white text-xs">
      {/* 头部:工具名徽章 + 主摘要 + 状态;有细节时整行可点开 */}
      <button
        type="button"
        disabled={!details}
        aria-expanded={details ? open : undefined}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start gap-2 px-2.5 py-1.5 text-left disabled:cursor-default"
      >
        <span className="mt-px shrink-0 rounded bg-brand-50 px-1.5 py-0.5 font-mono text-[11px] font-medium text-brand-700 ring-1 ring-brand-100">
          {call.name}
        </span>
        <span className="min-w-0 flex-1 whitespace-pre-wrap break-words font-mono text-slate-600">{summary}</span>
        <span className="mt-0.5 shrink-0" aria-hidden>
          {!result ? (
            <span className="block h-3 w-3 animate-spin rounded-full border-[1.5px] border-slate-200 border-t-brand-500" />
          ) : error ? (
            <span className="font-semibold text-red-500">✕</span>
          ) : (
            <span className="font-semibold text-brand-600">✓</span>
          )}
        </span>
        {details && <span className="mt-0.5 shrink-0 text-slate-400">{open ? "▾" : "▸"}</span>}
      </button>

      {/* 展开:完整写入内容 / 参数 */}
      {open && details && (
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words border-t border-slate-100 bg-slate-50 px-2.5 py-2 font-mono text-slate-600">
          {details}
        </pre>
      )}

      {/* 结果:输出或错误(成功 teal 侧、出错红底) */}
      {result && result.content && (
        <pre
          className={`max-h-60 overflow-auto whitespace-pre-wrap break-words border-t px-2.5 py-2 font-mono ${
            error ? "border-red-100 bg-red-50 text-red-700" : "border-slate-100 bg-slate-50 text-slate-600"
          }`}
        >
          {result.content}
        </pre>
      )}
    </div>
  )
}
