// 分段控件:枚举项的更优雅替代(替代原生 <select>)。一条 pill 轨道,选中项是浮起的白卡。
// 借鉴 iOS / Linear / Vercel 的 segmented control。
export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
}) {
  return (
    <div className="inline-flex rounded-xl bg-slate-100 p-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-lg px-3 py-1.5 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-200 ${
            value === o.value
              ? "bg-white text-brand-700 shadow-sm"
              : "text-slate-500 hover:text-slate-700"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
