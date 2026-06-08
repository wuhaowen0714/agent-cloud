import type { ReactNode } from "react"

/** 标签 + 控件 + 提示/错误 的统一排布。 */
export function Field({
  label,
  hint,
  error,
  children,
}: {
  label?: string
  hint?: string
  error?: string
  children: ReactNode
}) {
  return (
    <div className="space-y-1.5">
      {label && <label className="block text-xs font-medium text-slate-600">{label}</label>}
      {children}
      {error ? (
        <p className="text-xs text-red-600">{error}</p>
      ) : hint ? (
        <p className="text-xs text-slate-400">{hint}</p>
      ) : null}
    </div>
  )
}
