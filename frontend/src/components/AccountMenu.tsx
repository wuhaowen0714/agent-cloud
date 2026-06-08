import { useEffect, useRef, useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"

/** 贴底账户区:首字母圆头像 + 邮箱;点开菜单:工作区文件 / 登出。(Provider Keys 入口留待 Plan C。) */
export function AccountMenu() {
  const user = useStore((s) => s.user)
  const logout = useStore((s) => s.logout)
  const toggleFileDrawer = useStore((s) => s.toggleFileDrawer)
  const openSettings = useStore((s) => s.openSettings)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  if (!user) return null
  const initial = user.email.charAt(0).toUpperCase()
  const item = "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-slate-600 hover:bg-slate-50"

  const doLogout = async () => {
    setOpen(false)
    await api.logout().catch(() => {}) // 吊销服务端 refresh;网络失败也照常本地登出
    logout()
  }

  return (
    <div ref={ref} className="relative">
      {open && (
        <div className="absolute bottom-full left-0 right-0 z-30 mb-1 overflow-hidden rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
          <button
            className={item}
            onClick={() => {
              toggleFileDrawer()
              setOpen(false)
            }}
          >
            <span className="w-3.5 shrink-0 text-center">📁</span>
            <span>工作区文件</span>
          </button>
          <button
            className={item}
            onClick={() => {
              openSettings("keys")
              setOpen(false)
            }}
          >
            <span className="w-3.5 shrink-0 text-center">🔑</span>
            <span>Provider Keys</span>
          </button>
          <button className={`${item} hover:text-red-600`} onClick={doLogout}>
            <span className="w-3.5 shrink-0 text-center">⏻</span>
            <span>登出</span>
          </button>
        </div>
      )}
      <button
        className="flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-left hover:bg-slate-50"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-600 text-xs font-semibold text-white">
          {initial}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm text-slate-700">{user.email}</span>
        <span className="shrink-0 text-xs text-slate-400">▾</span>
      </button>
    </div>
  )
}
