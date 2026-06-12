import { MoreHorizontal } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"

export interface RowMenuItem {
  label: string
  danger?: boolean
  confirmLabel?: string // 有值 → 行内二次确认:第一次点击变此文案,再点才执行
  onSelect: () => void | Promise<void>
}

// 侧栏行尾「…」菜单:hover/选中显形;onSelect 抛错(如删除撞 409)原位短提示后复位。
export function RowMenu({
  items,
  ariaLabel,
  visible = false,
}: {
  items: RowMenuItem[]
  ariaLabel: string
  visible?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState({ top: 0, right: 8 })
  const [confirming, setConfirming] = useState<number | null>(null)
  const [failed, setFailed] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const close = () => {
    if (timer.current) clearTimeout(timer.current) // 失败定时器不许跨次开关残留
    setOpen(false)
    setConfirming(null)
    setFailed(false)
  }

  const openMenu = () => {
    // 浮层 portal 到 body + fixed 定位:列表容器 overflow-auto 会裁剪 absolute 浮层;
    // 而留在侧栏面板内的 fixed 又会被面板的 backdrop-blur 变成「相对面板」解析坐标
    // (backdrop-filter 与 transform 同款地成为 fixed 后代的包含块)→ 飞出屏幕外。
    // 打开瞬间按触发钮定位;开着滚动属边缘情况,点外面即收起。
    const r = triggerRef.current?.getBoundingClientRect()
    if (r) setPos({ top: r.bottom + 4, right: Math.max(8, window.innerWidth - r.right) })
    setOpen(true)
  }

  useEffect(() => {
    if (!open) return
    const onDoc = (e: Event) => {
      const t = e.target as Node
      // 菜单在 portal 里,不再是触发钮的 DOM 后代 → 两个 ref 都要查
      if (!ref.current?.contains(t) && !menuRef.current?.contains(t)) close()
    }
    document.addEventListener("pointerdown", onDoc)
    return () => document.removeEventListener("pointerdown", onDoc)
  }, [open])

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )

  const run = async (i: number) => {
    const it = items[i]
    if (it.confirmLabel && confirming !== i) {
      setConfirming(i)
      return
    }
    try {
      await it.onSelect()
      close()
    } catch {
      setFailed(true) // 典型:删除撞 409(回合进行中)
      timer.current = setTimeout(close, 2000)
    }
  }

  return (
    <div
      ref={ref}
      className="relative"
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.stopPropagation()
          close()
        }
      }}
    >
      <button
        ref={triggerRef}
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => (open ? close() : openMenu())}
        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-slate-400 transition hover:bg-white hover:text-slate-700 focus-visible:opacity-100 ${
          visible || open ? "opacity-100" : "opacity-0 group-hover:opacity-100"
        }`}
      >
        <MoreHorizontal size={14} />
      </button>
      {open &&
        createPortal(
          <div
            ref={menuRef}
            role="menu"
            style={{ top: pos.top, right: pos.right }}
            className="fixed z-30 w-44 rounded-xl border border-slate-200 bg-white p-1 shadow-pop"
          >
          {failed ? (
            <div className="px-2.5 py-1.5 text-xs text-red-600">进行中,无法删除</div>
          ) : (
            items.map((it, i) => (
              <button
                key={it.label}
                type="button"
                role="menuitem"
                onClick={() => void run(i)}
                className={`flex w-full items-center rounded-lg px-2.5 py-1.5 text-left text-sm ${
                  confirming === i
                    ? "bg-red-50 font-medium text-red-700"
                    : it.danger
                      ? "text-red-600 hover:bg-red-50"
                      : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {confirming === i ? it.confirmLabel : it.label}
              </button>
            ))
          )}
          </div>,
          document.body,
        )}
    </div>
  )
}
