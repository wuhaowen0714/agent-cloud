import { Check, ChevronDown } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { findProvider } from "../../models"
import { useProviderOptions } from "./useModelOptions"

// 通用小下拉(provider / model 共用):受控 value,选项点选回调。浮层点外关闭、贴底自动向上。
function Dropdown({
  value,
  options,
  onSelect,
  variant,
  ariaLabel,
}: {
  value: string
  options: string[]
  onSelect: (v: string) => void
  variant: "chip" | "field"
  ariaLabel: string
}) {
  const [open, setOpen] = useState(false)
  const [up, setUp] = useState(false)
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
      setUp(below < 280 && r.top > below) // composer 贴底 → 向上;设置页 → 向下
    }
    setOpen(true)
  }

  const triggerCls =
    variant === "field"
      ? "flex w-full items-center justify-between gap-2 rounded-xl border border-slate-200 bg-slate-100/70 px-3.5 py-2.5 text-sm transition hover:border-slate-300 hover:bg-slate-50 focus-visible:outline-none focus-visible:border-brand-400 focus-visible:bg-white"
      : "inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"

  return (
    <div
      ref={ref}
      className={variant === "field" ? "relative flex-1" : "relative inline-block"}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.stopPropagation()
          setOpen(false)
        }
      }}
    >
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => (open ? setOpen(false) : openMenu())}
        className={triggerCls}
      >
        <span
          className={
            variant === "field"
              ? "min-w-0 flex-1 truncate text-left text-slate-800"
              : "max-w-[12rem] truncate"
          }
        >
          {value || "—"}
        </span>
        <ChevronDown size={variant === "field" ? 15 : 13} className="shrink-0 text-slate-400" />
      </button>
      {open && (
        <div
          role="listbox"
          className={`absolute z-30 max-h-72 min-w-[9rem] overflow-auto rounded-xl border border-slate-200 bg-white p-1.5 shadow-pop ${
            variant === "field" ? "left-0 right-0" : "left-0"
          } ${up ? "bottom-full mb-1.5" : "top-full mt-1.5"}`}
        >
          {options.length === 0 && (
            <div className="px-2.5 py-1.5 text-sm text-slate-400">无可用模型</div>
          )}
          {options.map((o) => (
            <button
              key={o}
              type="button"
              role="option"
              aria-selected={o === value}
              onClick={() => {
                onSelect(o)
                setOpen(false)
              }}
              className="flex w-full min-w-0 items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm hover:bg-slate-100 focus-visible:bg-slate-100 focus-visible:outline-none"
            >
              <span className="flex w-4 shrink-0 justify-center text-brand-600">
                {o === value && <Check size={14} />}
              </span>
              <span className="min-w-0 flex-1 truncate text-slate-700">{o}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// 图一两栏(session 级):Provider + Model。选 provider 切到其 credentialId,model 保持当前
// (若仍在该 provider)否则取其首个;选 model 保持当前 provider。写入由 onChange 落到 session。
export function ModelMenu({
  model,
  credentialId,
  onChange,
  variant = "field",
}: {
  model: string
  credentialId: string | null
  onChange: (model: string, credentialId: string | null) => void
  variant?: "chip" | "field"
}) {
  const { providers } = useProviderOptions()
  const current = findProvider(providers, credentialId)
  return (
    <div className={variant === "field" ? "flex gap-2" : "inline-flex items-center gap-1"}>
      <Dropdown
        variant={variant}
        ariaLabel="provider"
        value={current.name}
        options={providers.map((p) => p.name)}
        onSelect={(name) => {
          const p = providers.find((x) => x.name === name)
          if (!p) return
          const nextModel = p.models.includes(model) ? model : (p.models[0] ?? "")
          onChange(nextModel, p.credentialId)
        }}
      />
      <Dropdown
        variant={variant}
        ariaLabel="model"
        value={model}
        options={current.models}
        onSelect={(m) => onChange(m, current.credentialId)}
      />
    </div>
  )
}
