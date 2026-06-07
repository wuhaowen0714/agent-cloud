import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "../../api/client"
import { useStore } from "../../store"
import type { FileEntry } from "../../types"
import { FileBreadcrumb } from "./FileBreadcrumb"
import { FileList } from "./FileList"
import { FilePreview } from "./FilePreview"
import { FileToolbar } from "./FileToolbar"

export function FileDrawer() {
  const open = useStore((s) => s.fileDrawerOpen)
  const toggle = useStore((s) => s.toggleFileDrawer)
  const userId = useStore((s) => s.userId)
  const [path, setPath] = useState("")
  const [preview, setPreview] = useState<FileEntry | null>(null)
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: ["files", userId] })

  const { data: entries = [] } = useQuery({
    queryKey: ["files", userId, path],
    queryFn: () => api.listFiles(userId!, path),
    enabled: open && !!userId,
  })

  if (!open || !userId) return null
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20" onClick={toggle} />
      <aside
        className="fixed right-0 top-0 z-50 flex h-full w-[28rem] max-w-[90vw] flex-col border-l border-slate-200 bg-white shadow-xl"
        onDragOver={(e) => e.preventDefault()}
        onDrop={async (e) => {
          e.preventDefault()
          const files = Array.from(e.dataTransfer.files)
          if (files.length) {
            await api.uploadFiles(userId, path, files)
            refresh()
          }
        }}
      >
        <header className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
          <span className="text-sm font-semibold text-slate-800">文件</span>
          <button className="text-slate-400 hover:text-slate-700" onClick={toggle}>
            ✕
          </button>
        </header>
        <FileBreadcrumb path={path} onNavigate={setPath} />
        <FileToolbar userId={userId} path={path} onChanged={refresh} />
        <FileList
          entries={entries}
          userId={userId}
          onOpenDir={(e) => setPath(e.path)}
          onPreview={setPreview}
          onChanged={refresh}
        />
        <div className="border-t border-slate-100 px-3 py-1 text-center text-[11px] text-slate-300">
          拖拽文件到此处上传
        </div>
      </aside>
      {preview && <FilePreview userId={userId} entry={preview} onClose={() => setPreview(null)} />}
    </>
  )
}
