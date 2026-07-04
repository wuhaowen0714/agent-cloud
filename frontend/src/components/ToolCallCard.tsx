import { useEffect, useState } from "react"
import { api } from "../api/client"
import type { ToolProgress } from "../blocks"
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
  if (call.name === "edit") return { summary: String(a.path ?? ""), details: null } // diff 专区渲染
  if (call.name === "generate_image" || call.name === "edit_image") {
    return { summary: String(a.prompt ?? ""), details: null }
  }
  const keys = Object.keys(a)
  return { summary: keys.length ? JSON.stringify(a) : "", details: keys.length ? JSON.stringify(a, null, 2) : null }
}

// edit 工具的 edits 参数 → 结构化(不可信模型输出,逐项容错)。
export function parseEdits(args: Record<string, unknown>): { old_text: string; new_text: string }[] {
  const raw = args?.edits
  if (!Array.isArray(raw)) return []
  const out: { old_text: string; new_text: string }[] = []
  for (const e of raw) {
    if (typeof e !== "object" || e === null) continue
    const { old_text, new_text } = e as { old_text?: unknown; new_text?: unknown }
    if (typeof old_text !== "string" || typeof new_text !== "string") continue
    out.push({ old_text, new_text })
  }
  return out
}

// edit 的红绿 diff 区:old_text 整块红(- 前缀)、new_text 整块绿(+ 前缀)。edit 是「精确
// 替换」,直接呈现被换走/换来的文本就是最诚实的 diff,不做行内 LCS。
function EditDiff({ edits }: { edits: { old_text: string; new_text: string }[] }) {
  return (
    <div className="max-h-72 overflow-auto border-t border-slate-100 bg-slate-50 px-2.5 py-2 font-mono">
      {edits.map((e, i) => (
        <div key={`${i}-${e.old_text.slice(0, 12)}`} className={i > 0 ? "mt-2 border-t border-dashed border-slate-200 pt-2" : ""}>
          {e.old_text.split("\n").map((line, j) => (
            <div key={`o${j}`} className="whitespace-pre-wrap break-words bg-red-50 text-red-700">
              <span className="select-none text-red-400">- </span>
              {line}
            </div>
          ))}
          {e.new_text.split("\n").map((line, j) => (
            <div key={`n${j}`} className="whitespace-pre-wrap break-words bg-emerald-50 text-emerald-700">
              <span className="select-none text-emerald-500">+ </span>
              {line}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function fmtChars(n: number): string {
  return n < 1000 ? `${n}` : `${(n / 1000).toFixed(1)}k`
}

// generate_image 成功结果文本里嵌着落盘路径(worker 回填 "Generated image saved to media/picture/..")。
const IMG_PATH_RE = /(media\/picture\/[^\s"']+\.(?:png|jpe?g|webp|gif))/i

// 把生成的图片在卡片内大图展示。<img> 带不了 Bearer,故用带 token 的 fetch 取回 blob 生成本地
// object URL(同 FilePreview);卸载时 revoke 释放,避免内存泄漏。
function GeneratedImage({ path }: { path: string }) {
  const [url, setUrl] = useState<string | null>(null)
  const [err, setErr] = useState(false)
  useEffect(() => {
    let alive = true
    let created: string | null = null
    api
      .previewUrl(path)
      .then((u) => {
        if (!alive) {
          URL.revokeObjectURL(u)
          return
        }
        created = u
        setUrl(u)
      })
      .catch(() => alive && setErr(true))
    return () => {
      alive = false
      if (created) URL.revokeObjectURL(created)
    }
  }, [path])

  if (err) {
    return (
      <div className="border-t border-slate-100 px-2.5 py-2 text-slate-400">
        图片加载失败:{path}
      </div>
    )
  }
  if (!url) {
    return (
      <div className="flex items-center gap-2 border-t border-slate-100 px-2.5 py-2 text-slate-400">
        <span className="block h-3 w-3 animate-spin rounded-full border-[1.5px] border-slate-200 border-t-brand-500" />
        加载图片中…
      </div>
    )
  }
  return (
    <div className="border-t border-slate-100 bg-slate-50 p-2">
      <img src={url} alt={path} className="max-h-96 max-w-full rounded-md" />
    </div>
  )
}

// 危险操作拦截结果里的批准码(worker danger.py 契约;含码即渲染确认按钮)
const APPROVAL_RE = /批准码\s*([a-f0-9]{16})/

export function ToolCallCard({
  call,
  result,
  progress,
  onApprove,
}: {
  call: ToolCall
  result?: ToolResult
  progress?: ToolProgress
  onApprove?: (text: string) => void
}) {
  const [open, setOpen] = useState(false)
  const { summary, details } = describe(call)
  const error = result?.is_error ?? false
  // generate_image / edit_image 成功:从结果文本解析落盘路径,卡片内直接渲染图(常显,不随折叠)。
  const imagePath =
    (call.name === "generate_image" || call.name === "edit_image") && result && !error
      ? (result.content.match(IMG_PATH_RE)?.[1] ?? null)
      : null
  // 失败结果默认展开(错误通常要立刻看);成功保持折叠。仅在 error 由 false→true 时触发一次,
  // 故用户手动收起后不会被反弹。
  useEffect(() => {
    if (error) setOpen(true)
  }, [error])

  if (progress) {
    // 参数生成中(LLM 流式累积):只给轻量进度,不渲染内容。ToolCallStarted 到达后
    // 上游原位替换为真卡(progress 清空),自然落回下方正常分支。
    const counter =
      `已生成 ${fmtChars(progress.argsChars)} 字符` +
      (progress.lines >= 2 ? ` · 约 ${progress.lines} 行` : "")
    return (
      <div className="my-1.5 overflow-hidden rounded-lg border border-l-2 border-slate-200 border-l-brand-200 bg-white text-xs">
        <div className="flex w-full items-center gap-2 px-2.5 py-1.5">
          <span className="shrink-0 rounded bg-brand-50 px-1.5 py-0.5 font-mono text-[11px] font-medium text-brand-700 ring-1 ring-brand-100">
            {call.name}
          </span>
          {progress.path && (
            <span className="min-w-0 truncate font-mono text-slate-600">{progress.path}</span>
          )}
          <span className="min-w-0 flex-1 truncate text-slate-400">{counter}</span>
          <span className="shrink-0" aria-hidden>
            <span className="block h-3 w-3 animate-spin rounded-full border-[1.5px] border-slate-200 border-t-brand-500" />
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className="my-1.5 overflow-hidden rounded-lg border border-l-2 border-slate-200 border-l-brand-200 bg-white text-xs">
      {/* 头部:工具名徽章 + 主摘要 + 状态;有细节时整行可点开 */}
      <button
        type="button"
        disabled={call.name !== "edit" && !details && !result?.content}
        aria-expanded={call.name === "edit" || details || result?.content ? open : undefined}
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
        {(call.name === "edit" || details || result?.content) && (
          <span className="mt-0.5 shrink-0 text-slate-400">{open ? "▾" : "▸"}</span>
        )}
      </button>

      {/* generate_image:成功时把生成的图片在卡片内直接大图展示(不随折叠,常显) */}
      {imagePath && <GeneratedImage path={imagePath} />}

      {/* edit:展开时渲染红绿 diff(替代参数 JSON) */}
      {open && call.name === "edit" && (
        <EditDiff edits={parseEdits((call.arguments ?? {}) as Record<string, unknown>)} />
      )}

      {/* 展开:完整写入内容 / 参数 */}
      {open && details && (
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words border-t border-slate-100 bg-slate-50 px-2.5 py-2 font-mono text-slate-600">
          {details}
        </pre>
      )}

      {/* 危险操作被拦:一键批准 —— 发送含批准码的确认消息,agent 下一回合重试即放行 */}
      {result?.is_error && onApprove && APPROVAL_RE.test(result.content) && (
        <div className="flex items-center gap-2 border-t border-amber-200 bg-amber-50 px-2.5 py-1.5">
          <span className="min-w-0 flex-1 text-amber-700">此操作有破坏性,已被拦截,需你确认</span>
          <button
            type="button"
            onClick={() => {
              const fp = result.content.match(APPROVAL_RE)?.[1]
              if (fp) onApprove(`允许执行该操作(批准码 ${fp})`)
            }}
            className="shrink-0 rounded-md bg-amber-600 px-2 py-1 font-medium text-white hover:bg-amber-700"
          >
            允许执行并继续
          </button>
        </div>
      )}

      {/* 结果:输出或错误(成功 teal 侧、出错红底)。默认折叠,随头部 open 展开(失败自动展开)。 */}
      {open && result && result.content && (
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
