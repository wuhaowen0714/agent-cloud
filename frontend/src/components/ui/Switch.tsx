// 拨动开关:布尔/启用项的更优雅替代(替代裸 checkbox)。iOS 风。
// label 用作 aria-label —— 可见文案是同行的兄弟节点、与开关无程序关联,屏幕阅读器
// 否则只会读到"switch on/off"而不知道开关的是什么。
export function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: () => void
  label?: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={onChange}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-100/70 ${
        checked ? "bg-brand-500" : "bg-slate-300"
      }`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
          checked ? "translate-x-4" : "translate-x-0.5"
        }`}
      />
    </button>
  )
}
