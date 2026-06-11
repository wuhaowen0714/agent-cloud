import "@xterm/xterm/css/xterm.css"
import { X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { useStore } from "../../store"
import { useTerminalSocket } from "./useTerminalSocket"

interface Rect {
  x: number
  y: number
  w: number
  h: number
}
const MIN_W = 360
const MIN_H = 200
const KEY = "ac.terminal.rect"

function loadRect(): Rect {
  try {
    const r = JSON.parse(localStorage.getItem(KEY) ?? "")
    if (r && typeof r.x === "number") return r
  } catch {
    /* 无存档:用默认 */
  }
  // 默认:右下偏中,留出边距
  const w = Math.min(760, window.innerWidth - 80)
  const h = Math.min(420, window.innerHeight - 160)
  return { x: Math.max(40, window.innerWidth - w - 48), y: Math.max(40, window.innerHeight - h - 64), w, h }
}

// Ghostty 风悬浮终端:深色圆角浮窗,标题栏拖动、右下角 resize,位置/尺寸存 localStorage。
// createPortal 到 body,避开祖先 backdrop-filter / overflow 对 fixed 的裁剪(同 RowMenu 教训)。
export function TerminalWindow() {
  const toggleTerminal = useStore((s) => s.toggleTerminal)
  const [rect, setRect] = useState<Rect>(loadRect)
  const bodyRef = useRef<HTMLDivElement>(null)
  const { status, reconnect } = useTerminalSocket(bodyRef)

  // 拖动 / resize:用指针事件,移动期间在 document 上监听,松开落库 localStorage。
  const drag = useRef<{ mode: "move" | "resize"; px: number; py: number; r: Rect } | null>(null)
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const d = drag.current
      if (!d) return
      const dx = e.clientX - d.px
      const dy = e.clientY - d.py
      if (d.mode === "move") {
        const x = Math.min(Math.max(0, d.r.x + dx), window.innerWidth - 80)
        const y = Math.min(Math.max(0, d.r.y + dy), window.innerHeight - 40)
        setRect({ ...d.r, x, y })
      } else {
        setRect({ ...d.r, w: Math.max(MIN_W, d.r.w + dx), h: Math.max(MIN_H, d.r.h + dy) })
      }
    }
    const onUp = () => {
      if (drag.current) {
        drag.current = null
        setRect((r) => {
          localStorage.setItem(KEY, JSON.stringify(r))
          return r
        })
      }
    }
    document.addEventListener("pointermove", onMove)
    document.addEventListener("pointerup", onUp)
    return () => {
      document.removeEventListener("pointermove", onMove)
      document.removeEventListener("pointerup", onUp)
    }
  }, [])

  // Esc 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") toggleTerminal()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [toggleTerminal])

  const start = (mode: "move" | "resize") => (e: React.PointerEvent) => {
    e.preventDefault()
    drag.current = { mode, px: e.clientX, py: e.clientY, r: rect }
  }

  return createPortal(
    <div
      role="dialog"
      aria-label="终端"
      className="fixed z-40 flex flex-col overflow-hidden rounded-xl border border-slate-700 bg-[#1a1b26] shadow-2xl"
      style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }}
    >
      {/* 标题栏:拖动手柄 */}
      <div
        onPointerDown={start("move")}
        className="flex cursor-move items-center justify-between border-b border-slate-700/70 bg-[#16161e] px-3 py-1.5 text-xs text-slate-300 select-none"
      >
        <span className="font-medium">终端 · 工作区</span>
        <button
          type="button"
          aria-label="关闭终端"
          onClick={toggleTerminal}
          className="rounded p-0.5 text-slate-400 hover:bg-slate-700 hover:text-slate-100"
        >
          <X size={14} />
        </button>
      </div>
      {/* xterm 容器 */}
      <div ref={bodyRef} className="min-h-0 flex-1 bg-[#1a1b26] p-1.5" />
      {/* 断开/重连浮层 */}
      {status === "closed" && (
        <div className="absolute inset-0 top-8 flex flex-col items-center justify-center gap-2 bg-[#1a1b26]/85 text-sm text-slate-300">
          <span>连接已断开</span>
          <button
            type="button"
            onClick={reconnect}
            className="rounded-lg border border-slate-600 px-3 py-1 text-slate-200 hover:bg-slate-700"
          >
            点击重连
          </button>
        </div>
      )}
      {/* 右下角 resize 手柄 */}
      <div
        onPointerDown={start("resize")}
        aria-label="调整终端大小"
        className="absolute bottom-0 right-0 h-4 w-4 cursor-nwse-resize"
        style={{
          background:
            "linear-gradient(135deg, transparent 50%, rgb(71 85 105) 50%, rgb(71 85 105) 60%, transparent 60%, transparent 70%, rgb(71 85 105) 70%, rgb(71 85 105) 80%, transparent 80%)",
        }}
      />
    </div>,
    document.body,
  )
}
