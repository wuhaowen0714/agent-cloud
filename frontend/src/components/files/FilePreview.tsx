import { useEffect, useState } from "react"
import { api } from "../../api/client"
import { previewKind } from "../../files"
import type { FileEntry } from "../../types"

export function FilePreview({ userId, entry, onClose }: { userId: string; entry: FileEntry; onClose: () => void }) {
  const kind = previewKind(entry)
  const url = api.fileRawUrl(userId, entry.path)
  const [text, setText] = useState<string | null>(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    if (kind !== "text") return
    let alive = true
    fetch(url)
      .then((r) => (r.ok ? r.text() : Promise.reject(r.status)))
      .then((t) => alive && setText(t))
      .catch(() => alive && setErr(true))
    return () => {
      alive = false
    }
  }, [url, kind])

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-6" onClick={onClose}>
      <div
        className="flex max-h-[85vh] w-[44rem] max-w-[92vw] flex-col rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
          <span className="truncate font-mono text-sm text-slate-700">{entry.name}</span>
          <div className="flex shrink-0 gap-3 text-sm">
            <a className="text-brand-600 hover:text-brand-700" href={api.fileRawUrl(userId, entry.path, true)}>
              下载
            </a>
            <button className="text-slate-400 hover:text-slate-700" onClick={onClose}>
              ✕
            </button>
          </div>
        </header>
        <div className="overflow-auto p-3">
          {kind === "image" && <img src={url} alt={entry.name} className="mx-auto max-h-[70vh]" />}
          {kind === "text" &&
            (err ? (
              <div className="text-sm text-red-600">无法预览,请下载查看。</div>
            ) : (
              <pre className="whitespace-pre-wrap break-words font-mono text-xs text-slate-700">
                {text ?? "加载中…"}
              </pre>
            ))}
          {kind === "download" && (
            <div className="py-8 text-center text-sm text-slate-500">
              文件较大或为二进制,无法预览。
              <a className="text-brand-600 hover:underline" href={api.fileRawUrl(userId, entry.path, true)}>
                点此下载
              </a>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
