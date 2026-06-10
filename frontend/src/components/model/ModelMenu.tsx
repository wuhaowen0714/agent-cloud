import { Check, ChevronDown, Plus, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useModelOptions } from "./useModelOptions"

// 模型选单(仿 Claude Code):受控 value/onChange;选项 = 预设 ∪ 在用 ∪ 自定义。
// 自己不 patch agent——composer 用 onChange 立即落库,设置页用它改本地草稿。
// 自定义条目 hover 可删;底部「添加模型…」即加即选。浮层范式沿用 SelectMenu。
export function ModelMenu({
  value,
  onChange,
  variant = "field",
}: {
  value: string
  onChange: (model: string) => void
  variant?: "chip" | "field"
}) {
  const { options, addModel, removeModel } = useModelOptions()
  const [open, setOpen] = useState(false)
  const [up, setUp] = useState(false)
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState("")
  const [addFailed, setAddFailed] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
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
      setUp(below < 320 && r.top > below) // composer 贴底 → 自然向上;设置页默认向下
    }
    setAdding(false)
    setDraft("")
    setAddFailed(false)
    setOpen(true)
  }
  const close = () => {
    setOpen(false)
    triggerRef.current?.focus()
  }
  const submitAdd = async () => {
    const m = draft.trim()
    if (!m) return
    // 与已有选项同名(预设/在用/自定义):直接选中、不落库——否则会产生被合并去重
    // 吞掉、列表里永不可见也删不掉的孤儿自定义行。
    if (options.some((o) => o.model === m)) {
      onChange(m)
      close()
      return
    }
    try {
      const saved = await addModel(m)
      onChange(saved) // 添加即选中
      close()
    } catch {
      setAddFailed(true) // 422/409/网络:就地提示,保留输入供修改
    }
  }

  const triggerCls =
    variant === "field"
      ? "flex w-full items-center justify-between gap-2 rounded-xl border border-slate-200 bg-slate-100/70 px-3.5 py-2.5 text-sm transition hover:border-slate-300 hover:bg-slate-50 focus-visible:outline-none focus-visible:border-brand-400 focus-visible:bg-white focus-visible:ring-4 focus-visible:ring-brand-100/70"
      : "inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"

  return (
    <div
      ref={ref}
      className={variant === "field" ? "relative" : "relative inline-block"}
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
        className={triggerCls}
      >
        <span
          className={
            variant === "field"
              ? "min-w-0 flex-1 truncate text-left text-slate-800"
              : "max-w-[16rem] truncate"
          }
        >
          {value}
        </span>
        <ChevronDown size={variant === "field" ? 15 : 13} className="shrink-0 text-slate-400" />
      </button>
      {open && (
        <div
          role="listbox"
          className={`absolute z-30 max-h-72 overflow-auto rounded-xl border border-slate-200 bg-white p-1.5 shadow-pop ${
            variant === "field" ? "left-0 right-0" : "left-0 w-72"
          } ${up ? "bottom-full mb-1.5" : "top-full mt-1.5"}`}
        >
          {options.map((o) => (
            <div key={o.model} className="group flex items-center">
              <button
                type="button"
                role="option"
                aria-selected={o.model === value}
                onClick={() => {
                  onChange(o.model)
                  close()
                }}
                className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm hover:bg-slate-100 focus-visible:bg-slate-100 focus-visible:outline-none"
              >
                <span className="flex w-4 shrink-0 justify-center text-brand-600">
                  {o.model === value && <Check size={14} />}
                </span>
                <span className="min-w-0 flex-1 truncate text-slate-700">{o.model}</span>
              </button>
              {o.custom && (
                <button
                  type="button"
                  aria-label={`删除 ${o.model}`}
                  onClick={() => void removeModel(o.custom!.id).catch(() => {})}
                  className="mr-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-slate-300 opacity-0 transition hover:bg-slate-100 hover:text-slate-600 focus-visible:opacity-100 group-hover:opacity-100"
                >
                  <X size={13} />
                </button>
              )}
            </div>
          ))}
          <div className="mt-1 border-t border-slate-100 pt-1">
            {adding ? (
              <>
                <input
                  autoFocus
                  value={draft}
                  maxLength={200}
                  placeholder="模型名,Enter 确认"
                  onChange={(e) => {
                    setDraft(e.target.value)
                    setAddFailed(false)
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault()
                      void submitAdd()
                    } else if (e.key === "Escape") {
                      e.stopPropagation() // 只退回列表,不关整个浮层
                      setAdding(false)
                      setDraft("")
                      setAddFailed(false)
                    }
                  }}
                  className="w-full rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100"
                />
                {addFailed && (
                  <div className="px-2.5 pt-1 text-xs text-red-600">添加失败,请重试</div>
                )}
              </>
            ) : (
              <button
                type="button"
                onClick={() => setAdding(true)}
                className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm text-slate-500 hover:bg-slate-100 hover:text-slate-700"
              >
                <Plus size={14} className="shrink-0 text-slate-400" />
                添加模型…
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
