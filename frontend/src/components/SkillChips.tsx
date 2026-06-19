import { Package, X } from "lucide-react"

// 选中的技能 chip:既用于 Composer 待发送区(传 onRemove 显示移除 ×),也用于消息气泡(只读)。
// 与「@文件附件」chip 区分:技能用 brand(teal)色 + 📦 图标。
export function SkillChips({
  names,
  onRemove,
  align = "start",
}: {
  names: string[]
  onRemove?: (index: number) => void
  align?: "start" | "end"
}) {
  if (!names.length) return null
  return (
    <div className={`flex flex-wrap gap-2 ${align === "end" ? "justify-end" : "justify-start"}`}>
      {names.map((n, i) => (
        <span
          key={n}
          className="flex items-center gap-1.5 rounded-lg border border-brand-200 bg-brand-50 px-2.5 py-1 text-xs text-brand-700"
        >
          <Package size={14} className="text-brand-500" aria-hidden />
          <span className="max-w-[14rem] truncate font-medium">{n}</span>
          {onRemove && (
            <button
              type="button"
              aria-label="移除技能"
              onClick={() => onRemove(i)}
              className="-mr-0.5 shrink-0 text-brand-400 hover:text-brand-700"
            >
              <X size={13} />
            </button>
          )}
        </span>
      ))}
    </div>
  )
}
