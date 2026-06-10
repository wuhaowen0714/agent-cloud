import { ChevronDown, KeyRound, LogOut } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"

/** 贴底账户区:首字母圆头像 + 邮箱;点开菜单:Provider Keys / 登出。
 * (工作区文件入口在主区顶栏 TopBar。) */
export function AccountMenu() {
  const user = useStore((s) => s.user)
  const logout = useStore((s) => s.logout)
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
  const item =
    "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm text-slate-600 hover:bg-slate-100"

  const doLogout = async () => {
    setOpen(false)
    await api.logout().catch(() => {}) // 吊销服务端 refresh;网络失败也照常本地登出
    logout()
  }

  return (
    <div ref={ref} className="relative">
      {open && (
        <div className="absolute bottom-full left-0 right-0 z-30 mb-1.5 rounded-xl border border-slate-200 bg-white p-1.5 shadow-pop">
          <button
            className={item}
            onClick={() => {
              openSettings("keys")
              setOpen(false)
            }}
          >
            <KeyRound size={15} className="shrink-0 text-slate-400" />
            <span>Provider Keys</span>
          </button>
          <button className={`${item} hover:text-red-600`} onClick={doLogout}>
            <LogOut size={15} className="shrink-0" />
            <span>登出</span>
          </button>
        </div>
      )}
      <button
        className="flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-left shadow-sm transition hover:border-slate-300 hover:bg-slate-50"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-brand-600 text-xs font-semibold text-white shadow-sm">
          {initial}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm text-slate-700">{user.email}</span>
        <ChevronDown size={14} className="shrink-0 text-slate-400" />
      </button>
    </div>
  )
}
