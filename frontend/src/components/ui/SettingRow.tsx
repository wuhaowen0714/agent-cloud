import type { ReactNode } from "react"

// 一行设置:label(+hint)在左、控件在右;block=true 时控件整行铺开(宽输入/文本域/chip 组)。
export function SettingRow({
  label,
  hint,
  block = false,
  children,
}: {
  label: string
  hint?: string
  block?: boolean
  children: ReactNode
}) {
  return block ? (
    <div className="px-3.5 py-3">
      <div className="text-sm text-slate-700">{label}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-400">{hint}</div>}
      <div className="mt-2">{children}</div>
    </div>
  ) : (
    <div className="flex items-center justify-between gap-4 px-3.5 py-3">
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm text-slate-700">{label}</div>
        {hint && <div className="truncate text-xs text-slate-400">{hint}</div>}
      </div>
      <div className="flex shrink-0 items-center gap-2">{children}</div>
    </div>
  )
}
