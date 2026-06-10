import { MoreHorizontal } from "lucide-react"
import { useEffect, useRef, useState } from "react"

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
  const [confirming, setConfirming] = useState<number | null>(null)
  const [failed, setFailed] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const close = () => {
    setOpen(false)
    setConfirming(null)
    setFailed(false)
  }

  useEffect(() => {
    if (!open) return
    const onDoc = (e: Event) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close()
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
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => (open ? close() : setOpen(true))}
        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-slate-400 transition hover:bg-white hover:text-slate-700 ${
          visible || open ? "opacity-100" : "opacity-0 group-hover:opacity-100"
        }`}
      >
        <MoreHorizontal size={14} />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-30 mt-1 w-44 rounded-xl border border-slate-200 bg-white p-1 shadow-pop"
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
        </div>
      )}
    </div>
  )
}
