import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"

// TopBar 开关弹层的共享壳:portal 到 body + fixed 定位 —— TopBar 的 backdrop-blur
// 会成为 fixed 后代的包含块(与 transform 同款),留在头部内坐标会解析错(同 RowMenu)。
// Esc / 点外关闭;锚点按钮自身排除在「点外」之外(其 onClick 负责开合,避免双触发)。
export function TogglePopover({
  anchorRef,
  title,
  onClose,
  children,
}: {
  anchorRef: React.RefObject<HTMLElement | null>
  title: string
  onClose: () => void
  children: React.ReactNode
}) {
  const panelRef = useRef<HTMLDivElement>(null)
  // 打开瞬间按锚点定位一次;开着滚动属边缘情况,点外即收
  const [pos] = useState(() => {
    const r = anchorRef.current?.getBoundingClientRect()
    return r
      ? { top: r.bottom + 6, right: Math.max(8, window.innerWidth - r.right) }
      : { top: 48, right: 16 }
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    const onDoc = (e: Event) => {
      const t = e.target as Node
      if (!panelRef.current?.contains(t) && !anchorRef.current?.contains(t)) onClose()
    }
    document.addEventListener("keydown", onKey)
    document.addEventListener("pointerdown", onDoc)
    return () => {
      document.removeEventListener("keydown", onKey)
      document.removeEventListener("pointerdown", onDoc)
    }
  }, [onClose, anchorRef])

  return createPortal(
    <div
      ref={panelRef}
      role="dialog"
      aria-label={title}
      style={pos}
      className="fixed z-30 w-72 rounded-xl border border-slate-200 bg-white p-1.5 shadow-pop"
    >
      <div className="px-2.5 pb-1 pt-1.5 text-xs font-medium text-slate-400">{title}</div>
      {children}
    </div>,
    document.body,
  )
}
