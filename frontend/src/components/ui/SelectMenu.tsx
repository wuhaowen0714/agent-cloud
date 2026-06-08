import { useEffect, useRef, useState } from "react"

type Opt = { value: string; label: string; hint?: string }

// 自绘下拉浮层(替代原生 <select>):闭合态是填充式按钮,展开是圆角阴影浮层 + 勾选高亮。
// 原生 select 的"展开列表"无法被 CSS 设计,这里把开/合两态都做成统一风格,并补回原生
// select 的可达性:aria-haspopup/expanded + listbox/option 语义、Esc 关闭并回焦触发器、
// 以及在下方空间不足时向上展开(规避抽屉 overflow-auto 对浮层的裁剪)。
export function SelectMenu({
  value,
  options,
  onChange,
  placeholder = "选择…",
}: {
  value: string
  options: Opt[]
  onChange: (v: string) => void
  placeholder?: string
}) {
  const [open, setOpen] = useState(false)
  const [up, setUp] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    // pointerdown 覆盖鼠标/触摸/触控笔的"点外面收起"。
    const onDoc = (e: Event) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("pointerdown", onDoc)
    return () => document.removeEventListener("pointerdown", onDoc)
  }, [open])

  const openMenu = () => {
    const r = triggerRef.current?.getBoundingClientRect()
    if (r) {
      const below = window.innerHeight - r.bottom
      setUp(below < 280 && r.top > below) // 下方放不下且上方更宽裕 → 向上展开
    }
    setOpen(true)
  }
  const close = () => {
    setOpen(false)
    triggerRef.current?.focus()
  }

  const cur = options.find((o) => o.value === value)
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
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => (open ? setOpen(false) : openMenu())}
        className="flex w-full items-center justify-between gap-2 rounded-xl border border-slate-200 bg-slate-100/70 px-3.5 py-2.5 text-sm transition hover:border-slate-300 hover:bg-slate-50 focus-visible:outline-none focus-visible:border-brand-400 focus-visible:bg-white focus-visible:ring-4 focus-visible:ring-brand-100/70"
      >
        <span className={`min-w-0 flex-1 truncate text-left ${cur ? "text-slate-800" : "text-slate-400"}`}>
          {cur?.label ?? placeholder}
        </span>
        <svg
          className="h-4 w-4 shrink-0 text-slate-400"
          viewBox="0 0 20 20"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        >
          <path d="M6 8l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div
          role="listbox"
          className={`absolute left-0 right-0 z-30 max-h-64 overflow-auto rounded-xl border border-slate-200 bg-white p-1.5 shadow-pop ${
            up ? "bottom-full mb-1.5" : "top-full mt-1.5"
          }`}
        >
          {options.map((o) => (
            <button
              key={o.value}
              type="button"
              role="option"
              aria-selected={o.value === value}
              onClick={() => {
                onChange(o.value)
                close()
              }}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm hover:bg-slate-100 focus-visible:bg-slate-100 focus-visible:outline-none"
            >
              <span className="w-3.5 shrink-0 text-brand-600">{o.value === value ? "✓" : ""}</span>
              <span className="min-w-0 flex-1 truncate text-slate-700">{o.label}</span>
              {o.hint && <span className="shrink-0 text-xs text-slate-400">{o.hint}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
