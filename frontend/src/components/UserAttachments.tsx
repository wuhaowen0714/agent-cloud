import { File as FileIcon, FileSpreadsheet, FileText, X } from "lucide-react"
import { useEffect, useState } from "react"
import { api } from "../api/client"

// 随消息上传的附件:图片渲染缩略图、其它文件渲染类型图标 + 文件名 chip。同一套渲染既用于
// 已发送的消息气泡(只读、右对齐),也用于 Composer 待发送区(传 onRemove 显示移除 ×、左对齐)。
// 路径是工作区相对路径(如 upload/cat.png);取图走带 token 的 previewUrl。

const IMG_EXT = /\.(png|jpe?g|webp|gif|bmp|svg)$/i

export function UserAttachments({
  paths,
  onRemove,
  align = "end",
}: {
  paths: string[]
  onRemove?: (index: number) => void
  align?: "start" | "end"
}) {
  return (
    <div className={`flex flex-wrap gap-2 ${align === "end" ? "justify-end" : "justify-start"}`}>
      {paths.map((p, i) => (
        <UserAttachment key={p} path={p} onRemove={onRemove ? () => onRemove(i) : undefined} />
      ))}
    </div>
  )
}

function UserAttachment({ path, onRemove }: { path: string; onRemove?: () => void }) {
  const name = path.split("/").pop() || path
  return IMG_EXT.test(path) ? (
    <Thumb path={path} alt={name} onRemove={onRemove} />
  ) : (
    <FileChip name={name} onRemove={onRemove} />
  )
}

// 工作区图片缩略图:<img> 带不了 Bearer,故 token'd fetch 取 blob 生成 object URL,卸载 revoke
// (同 ToolCallCard 的 GeneratedImage / FilePreview)。
function Thumb({ path, alt, onRemove }: { path: string; alt: string; onRemove?: () => void }) {
  const [url, setUrl] = useState<string | null>(null)
  const [err, setErr] = useState(false)
  useEffect(() => {
    let alive = true
    let created: string | null = null
    api
      .previewUrl(path)
      .then((u) => {
        if (!alive) return URL.revokeObjectURL(u)
        created = u
        setUrl(u)
      })
      .catch(() => alive && setErr(true))
    return () => {
      alive = false
      if (created) URL.revokeObjectURL(created)
    }
  }, [path])

  const inner = err ? (
    <div className="flex h-28 w-28 items-center justify-center rounded-xl bg-slate-100 text-xs text-slate-400">
      加载失败
    </div>
  ) : !url ? (
    <div className="flex h-28 w-28 items-center justify-center rounded-xl bg-slate-100" aria-busy>
      <span className="block h-4 w-4 animate-spin rounded-full border-[1.5px] border-slate-300 border-t-brand-500" />
    </div>
  ) : (
    <img
      src={url}
      alt={alt}
      className="h-28 w-28 rounded-xl object-cover shadow-sm ring-1 ring-slate-200"
    />
  )

  if (!onRemove) return inner
  return (
    <div className="relative">
      {inner}
      <button
        type="button"
        aria-label="移除附件"
        onClick={onRemove}
        className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full bg-slate-900/55 text-white shadow hover:bg-slate-900"
      >
        <X size={12} />
      </button>
    </div>
  )
}

function FileChip({ name, onRemove }: { name: string; onRemove?: () => void }) {
  const { Icon, color } = iconFor(name)
  return (
    <div className="flex max-w-[16rem] items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm">
      <Icon size={20} className={color} aria-hidden />
      <span className="truncate text-sm text-slate-700">{name}</span>
      {onRemove && (
        <button
          type="button"
          aria-label="移除附件"
          onClick={onRemove}
          className="-mr-1 shrink-0 text-slate-400 hover:text-slate-700"
        >
          <X size={15} />
        </button>
      )}
    </div>
  )
}

function iconFor(name: string): { Icon: typeof FileText; color: string } {
  const ext = name.toLowerCase().split(".").pop() || ""
  if (ext === "pdf") return { Icon: FileText, color: "text-red-500" }
  if (["xls", "xlsx", "xlsm", "csv", "tsv"].includes(ext))
    return { Icon: FileSpreadsheet, color: "text-green-600" }
  if (["doc", "docx"].includes(ext)) return { Icon: FileText, color: "text-blue-600" }
  if (["ppt", "pptx"].includes(ext)) return { Icon: FileText, color: "text-orange-500" }
  return { Icon: FileIcon, color: "text-slate-400" }
}
