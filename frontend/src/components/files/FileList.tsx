import { useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "../../api/client"
import { formatSize, isHiddenEntry } from "../../files"
import type { FileEntry } from "../../types"

// 下载:fetch(带 Bearer)→ blob URL → 触发 <a download> → 释放。<a href> 直链带不了 token。
async function downloadFile(e: FileEntry) {
  const url = await api.downloadUrl(e.path)
  const a = document.createElement("a")
  a.href = url
  a.download = e.name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0) // 同步 revoke 可能在某些浏览器取消下载,延后释放
}

export function FileList({
  entries, onOpenDir, onPreview, onChanged,
}: {
  entries: FileEntry[]
  onOpenDir: (e: FileEntry) => void
  onPreview: (e: FileEntry) => void
  onChanged: () => void
}) {
  const qc = useQueryClient()
  const del = useMutation({ mutationFn: (e: FileEntry) => api.deleteFile(e.path), onSuccess: onChanged })
  const rename = useMutation({
    mutationFn: ({ e, dst }: { e: FileEntry; dst: string }) => api.moveFile(e.path, dst),
    onSuccess: onChanged,
  })
  // 把一个含 SKILL.md 的工作区文件夹安装进技能池(agent 用 skill-creator 现写的成果一键可用)。
  const install = useMutation({
    mutationFn: (e: FileEntry) => api.installSkillFromWorkspace(e.path),
    onSuccess: (sk) => {
      qc.invalidateQueries({ queryKey: ["skills"] }) // 刷新技能列表/agent 设置里的技能池
      alert(`已安装技能:${sk.name}(去 agent 设置启用)`)
    },
    onError: (err) => alert(`安装失败:${String(err)}`),
  })

  // 点开头【目录】不显示(沙箱基础设施噪音);点文件保留(见 isHiddenEntry 注释)。
  // 仅前端隐藏——agent(bash/read_file)与 API 仍可访问。
  const visible = entries.filter((e) => !isHiddenEntry(e))
  if (visible.length === 0) {
    return <div className="flex-1 p-6 text-center text-sm text-slate-400">空目录</div>
  }
  return (
    <ul className="flex-1 divide-y divide-slate-50 overflow-auto">
      {visible.map((e) => (
        <li key={e.path} className="group flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-slate-50">
          <span className="shrink-0">{e.is_dir ? "📁" : "📄"}</span>
          <button
            className="min-w-0 flex-1 truncate text-left text-slate-700 hover:text-brand-600"
            onClick={() => (e.is_dir ? onOpenDir(e) : onPreview(e))}
            title={e.name}
          >
            {e.name}
          </button>
          {!e.is_dir && <span className="shrink-0 text-xs text-slate-400">{formatSize(e.size)}</span>}
          <span className="flex shrink-0 gap-1.5 text-xs opacity-0 group-hover:opacity-100">
            {e.is_dir && (
              <button
                className="text-slate-400 hover:text-brand-600"
                title="若该文件夹含 SKILL.md,安装为技能"
                onClick={() => install.mutate(e)}
              >
                安装为技能
              </button>
            )}
            {!e.is_dir && (
              <button className="text-slate-400 hover:text-brand-600" onClick={() => downloadFile(e)}>
                下载
              </button>
            )}
            <button
              className="text-slate-400 hover:text-brand-600"
              onClick={() => {
                const base = e.path.includes("/") ? e.path.slice(0, e.path.lastIndexOf("/") + 1) : ""
                const next = prompt("重命名为", e.name)
                if (!next || next === e.name) return
                // 点开头的文件夹会被列表隐藏 → 改完即失联(UI 内无入口改回),拦下
                if (e.is_dir && next.startsWith(".")) {
                  alert("以 . 开头的文件夹会被隐藏,请换个名称")
                  return
                }
                rename.mutate({ e, dst: base + next })
              }}
            >
              重命名
            </button>
            <button
              className="text-slate-400 hover:text-red-600"
              onClick={() => {
                if (confirm(`删除 ${e.name}?${e.is_dir ? "(含其中所有文件)" : ""}`)) del.mutate(e)
              }}
            >
              删除
            </button>
          </span>
        </li>
      ))}
    </ul>
  )
}
