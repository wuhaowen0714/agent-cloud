import { useMutation } from "@tanstack/react-query"
import { useRef } from "react"
import { api } from "../../api/client"

export function FileToolbar({ path, onChanged }: { path: string; onChanged: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const upload = useMutation({
    mutationFn: (files: File[]) => api.uploadFiles(path, files),
    onSuccess: onChanged,
  })
  const mkdir = useMutation({
    mutationFn: (name: string) => api.mkdir(path ? `${path}/${name}` : name),
    onSuccess: onChanged,
  })
  return (
    <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-1.5 text-xs">
      <button
        className="rounded bg-brand-600 px-2 py-1 text-white hover:bg-brand-700"
        onClick={() => inputRef.current?.click()}
      >
        上传
      </button>
      <input
        ref={inputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => {
          const fs = Array.from(e.target.files ?? [])
          if (fs.length) upload.mutate(fs)
          e.target.value = ""
        }}
      />
      <button
        className="rounded border border-slate-300 px-2 py-1 text-slate-600 hover:bg-slate-50"
        onClick={() => {
          const n = prompt("新建文件夹名称")
          if (n) mkdir.mutate(n)
        }}
      >
        新建文件夹
      </button>
      {upload.isPending && <span className="text-slate-400">上传中…</span>}
    </div>
  )
}
