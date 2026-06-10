import { useEffect, useState } from "react"
import { api } from "../../api/client"
import { previewKind } from "../../files"
import type { FileEntry } from "../../types"

export function FilePreview({ entry, onClose }: { entry: FileEntry; onClose: () => void }) {
  const kind = previewKind(entry)
  const [url, setUrl] = useState<string | null>(null) // 内联展示用的 blob object URL(图片/文本)
  const [text, setText] = useState<string | null>(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    // download 类(大/二进制)不预取,点下载时再 fetch;仅图片/文本预取以内联展示。
    if (kind !== "image" && kind !== "text") return
    let alive = true
    let created: string | null = null
    // <img>/<a> 带不了 Bearer → 用带 token 的 fetch 取回 blob,生成本地 object URL。
    api
      .previewUrl(entry.path)
      .then(async (u) => {
        if (!alive) {
          URL.revokeObjectURL(u)
          return
        }
        created = u
        setUrl(u)
        if (kind === "text") {
          const t = await fetch(u).then((r) => r.text()) // blob: URL 同源可直接读
          if (alive) setText(t)
        }
      })
      .catch(() => alive && setErr(true))
    return () => {
      alive = false
      if (created) URL.revokeObjectURL(created)
    }
  }, [entry.path, kind])

  const download = async () => {
    try {
      const u = await api.downloadUrl(entry.path)
      const a = document.createElement("a")
      a.href = u
      a.download = entry.name
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(u), 0) // 同步 revoke 可能在某些浏览器取消下载,延后释放
    } catch {
      setErr(true) // 下载失败不再静默(此前裸 await,点击毫无反馈)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/40 p-6 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-[44rem] max-w-[92vw] flex-col overflow-hidden rounded-2xl bg-white shadow-pop"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
          <span className="truncate font-mono text-sm text-slate-700">{entry.name}</span>
          <div className="flex shrink-0 gap-3 text-sm">
            <button className="text-brand-600 hover:text-brand-700" onClick={download}>
              下载
            </button>
            <button className="text-slate-400 hover:text-slate-700" onClick={onClose}>
              ✕
            </button>
          </div>
        </header>
        <div className="overflow-auto p-3">
          {err && <div className="text-sm text-red-600">无法预览,请下载查看。</div>}
          {!err && kind === "image" && url && (
            <img src={url} alt={entry.name} className="mx-auto max-h-[70vh]" />
          )}
          {!err && kind === "text" && (
            <pre className="whitespace-pre-wrap break-words font-mono text-xs text-slate-700">
              {text ?? "加载中…"}
            </pre>
          )}
          {!err && kind === "download" && (
            <div className="py-8 text-center text-sm text-slate-500">
              文件较大或为二进制,无法预览。
              <button className="ml-1 text-brand-600 hover:underline" onClick={download}>
                点此下载
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
