import { useMutation } from "@tanstack/react-query"
import { useRef } from "react"
import { api } from "../../api/client"
import { Button } from "../ui"

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
    <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2">
      <Button size="sm" onClick={() => inputRef.current?.click()}>
        ↑ 上传
      </Button>
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
      <Button
        size="sm"
        variant="secondary"
        onClick={() => {
          const n = prompt("新建文件夹名称")
          if (n) mkdir.mutate(n)
        }}
      >
        ＋ 文件夹
      </Button>
      {upload.isPending && <span className="text-xs text-slate-400">上传中…</span>}
    </div>
  )
}
