import { KeyRound, LogOut } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { api } from "../api/client"
import { useStore } from "../store"

/** rail 底部账户位:圆头像触发器;菜单 portal 到 body、贴触发器右上展开
 * (邮箱行 / Provider Keys / 登出)。portal + fixed:46px 的 rail 装不下 w-52 浮层,
 * 且 portal 免疫任何祖先 filter/transform 形成的包含块陷阱(面板的 backdrop-blur
 * 即此类,见 RowMenu 注释)。 */
export function AccountMenu() {
  const user = useStore((s) => s.user)
  const logout = useStore((s) => s.logout)
  const openSettings = useStore((s) => s.openSettings)
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState({ left: 0, bottom: 0 })
  const ref = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node
      // 菜单在 portal 里,不是触发器的 DOM 后代 → 两个 ref 都要查
      if (ref.current?.contains(t) || menuRef.current?.contains(t)) return
      setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  if (!user) return null
  const initial = user.email.charAt(0).toUpperCase()
  const item =
    "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm text-slate-600 hover:bg-slate-100"

  const openMenu = () => {
    // 锚定:菜单底边贴触发器底边,向右上方展开
    const r = ref.current?.getBoundingClientRect()
    if (r) setPos({ left: r.right + 8, bottom: window.innerHeight - r.bottom })
    setOpen(true)
  }

  const doLogout = async () => {
    setOpen(false)
    await api.logout().catch(() => {}) // 吊销服务端 refresh;网络失败也照常本地登出
    logout()
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label="账户"
        onClick={() => (open ? setOpen(false) : openMenu())}
        className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-brand-600 text-xs font-semibold text-white shadow-sm transition hover:ring-2 hover:ring-slate-300 hover:ring-offset-1"
      >
        {initial}
      </button>
      {open &&
        createPortal(
          <div
            ref={menuRef}
            style={{ left: pos.left, bottom: pos.bottom }}
            className="fixed z-30 w-52 rounded-xl border border-slate-200 bg-white p-1.5 shadow-pop"
          >
            <div className="truncate px-2.5 py-1.5 text-xs text-slate-400">{user.email}</div>
            <div className="mx-1 my-1 border-t border-slate-100" />
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
          </div>,
          document.body,
        )}
    </div>
  )
}
