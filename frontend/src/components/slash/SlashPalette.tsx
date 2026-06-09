export interface PaletteItem {
  title: string
  hint?: string
}

// composer 输入框上方的命令/建议浮层。键盘由 Composer 统一路由,这里只展示 + 鼠标选。
// 用 onMouseDown + preventDefault(而非 onClick)以免点选时 textarea 先失焦。
export function SlashPalette({
  items,
  selectedIndex,
  onSelect,
  onHover,
}: {
  items: PaletteItem[]
  selectedIndex: number
  onSelect: (index: number) => void
  onHover: (index: number) => void
}) {
  return (
    <div
      role="listbox"
      className="absolute bottom-full left-0 right-0 z-30 mb-2 max-h-72 overflow-auto rounded-xl border border-slate-200 bg-white p-1.5 shadow-pop"
    >
      {items.map((it, i) => (
        <button
          key={i}
          type="button"
          role="option"
          aria-selected={i === selectedIndex}
          onMouseDown={(e) => {
            e.preventDefault()
            onSelect(i)
          }}
          onMouseEnter={() => onHover(i)}
          className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-1.5 text-left text-sm ${
            i === selectedIndex ? "bg-slate-100" : "hover:bg-slate-50"
          }`}
        >
          <span className="min-w-0 flex-1 truncate text-slate-700">{it.title}</span>
          {it.hint && <span className="shrink-0 text-xs text-slate-400">{it.hint}</span>}
        </button>
      ))}
      <div className="border-t border-slate-100 px-2.5 pb-0.5 pt-1.5 text-[11px] text-slate-400">
        ↑↓ 选择 · Enter 执行 · Esc 关闭
      </div>
    </div>
  )
}
