import { File as FileIcon, FileSpreadsheet, FileText } from "lucide-react"
import { useEffect, useState } from "react"
import { api } from "../api/client"

// 用户消息里随文本上传的附件:图片渲染缩略图,其它文件渲染类型图标 + 文件名 chip。
// 路径是工作区相对路径(如 upload/cat.png);取图走带 token 的 previewUrl。

const IMG_EXT = /\.(png|jpe?g|webp|gif|bmp|svg)$/i

export function UserAttachments({ paths }: { paths: string[] }) {
  return (
    <div className="flex flex-wrap justify-end gap-2">
      {paths.map((p) => (
        <UserAttachment key={p} path={p} />
      ))}
    </div>
  )
}

function UserAttachment({ path }: { path: string }) {
  const name = path.split("/").pop() || path
  return IMG_EXT.test(path) ? <Thumb path={path} alt={name} /> : <FileChip name={name} />
}

// 工作区图片缩略图:<img> 带不了 Bearer,故 token'd fetch 取 blob 生成 object URL,卸载 revoke
// (同 ToolCallCard 的 GeneratedImage / FilePreview)。
function Thumb({ path, alt }: { path: string; alt: string }) {
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

  if (err)
    return (
      <div className="flex h-28 w-28 items-center justify-center rounded-xl bg-slate-100 text-xs text-slate-400">
        加载失败
      </div>
    )
  if (!url)
    return (
      <div className="flex h-28 w-28 items-center justify-center rounded-xl bg-slate-100" aria-busy>
        <span className="block h-4 w-4 animate-spin rounded-full border-[1.5px] border-slate-300 border-t-brand-500" />
      </div>
    )
  return (
    <img
      src={url}
      alt={alt}
      className="h-28 w-28 rounded-xl object-cover shadow-sm ring-1 ring-slate-200"
    />
  )
}

function FileChip({ name }: { name: string }) {
  const { Icon, color } = iconFor(name)
  return (
    <div className="flex max-w-[16rem] items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm">
      <Icon size={20} className={color} aria-hidden />
      <span className="truncate text-sm text-slate-700">{name}</span>
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
