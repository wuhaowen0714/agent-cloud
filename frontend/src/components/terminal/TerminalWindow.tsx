import "@xterm/xterm/css/xterm.css"
import { ChevronUp } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { useStore } from "../../store"
import { useTerminalSocket } from "./useTerminalSocket"

const MIN_H = 160
const KEY = "ac.terminal.height"

function loadHeight(): number {
  const h = Number(localStorage.getItem(KEY))
  if (Number.isFinite(h) && h >= MIN_H) return Math.min(h, Math.round(window.innerHeight * 0.85))
  return Math.round(window.innerHeight * 0.4)
}

// Ghostty quick-terminal 风:全视口宽、从顶部滑下的下拉面板(translateY 动画)。
// 关键语义:收起 ≠ 断开——本组件由 App 在首次打开后【常驻挂载】,terminalOpen 只驱动
// 滑入/滑出动画;收起时 WS/PTY/xterm 缓冲全保留,再展开时跑着的进程与屏幕内容原样还在。
// (刷新页面仍是新 shell:临时 PTY 语义,历史/cwd 经软状态恢复。)
// createPortal 到 body,避开祖先 backdrop-filter / overflow 对 fixed 的裁剪(同 RowMenu 教训)。
export function TerminalWindow() {
  const open = useStore((s) => s.terminalOpen)
  const toggleTerminal = useStore((s) => s.toggleTerminal)
  const [height, setHeight] = useState<number>(loadHeight)
  const panelRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const { status, reconnect, focus } = useTerminalSocket(bodyRef)

  // 首帧以收起态渲染,下一帧再应用展开态 → 首次挂载也有滑入动画
  const [entered, setEntered] = useState(false)
  useEffect(() => {
    const id = requestAnimationFrame(() => setEntered(true))
    return () => cancelAnimationFrame(id)
  }, [])
  const shown = open && entered

  // 底边拖拽调高度;松开落库 localStorage
  const drag = useRef<{ py: number; h: number } | null>(null)
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const d = drag.current
      if (!d) return
      const max = Math.round(window.innerHeight * 0.85)
      setHeight(Math.max(MIN_H, Math.min(max, d.h + (e.clientY - d.py))))
    }
    const onUp = () => {
      if (drag.current) {
        drag.current = null
        setHeight((h) => {
          localStorage.setItem(KEY, String(h))
          return h
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

  // Esc 收起——仅展开时监听(常驻挂载,收起后不能再抢 Esc)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") toggleTerminal()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [open, toggleTerminal])

  // 展开 → 滑入动画后聚焦 xterm;收起 → 若焦点还在面板内则移走(配合 aria-hidden)
  useEffect(() => {
    if (open) {
      const t = setTimeout(focus, 320)
      return () => clearTimeout(t)
    }
    const el = document.activeElement
    if (el instanceof HTMLElement && panelRef.current?.contains(el)) el.blur()
  }, [open, focus])

  return createPortal(
    <div
      ref={panelRef}
      role="dialog"
      aria-label="终端"
      aria-hidden={!open}
      className={`fixed inset-x-0 top-0 z-40 flex flex-col overflow-hidden rounded-b-xl border-x border-b border-slate-700 bg-[#1a1b26] shadow-2xl transition-transform duration-300 ease-out ${
        shown ? "translate-y-0" : "pointer-events-none -translate-y-full"
      }`}
      style={{ height }}
    >
      <div className="flex select-none items-center justify-between border-b border-slate-700/70 bg-[#16161e] px-3 py-1.5 text-xs text-slate-300">
        <span className="font-medium">终端 · 工作区</span>
        <button
          type="button"
          aria-label="收起终端"
          title="收起(Esc)——进程继续运行"
          onClick={toggleTerminal}
          className="rounded p-0.5 text-slate-400 hover:bg-slate-700 hover:text-slate-100"
        >
          <ChevronUp size={14} />
        </button>
      </div>
      {/* xterm 容器 */}
      <div ref={bodyRef} className="min-h-0 flex-1 bg-[#1a1b26] p-1.5" />
      {/* 断开浮层:真断开可重连;被接管(4001)只提示,重连会再被踢故不给重连 */}
      {(status === "closed" || status === "evicted") && (
        <div className="absolute inset-0 top-8 flex flex-col items-center justify-center gap-2 bg-[#1a1b26]/85 text-sm text-slate-300">
          <span>{status === "evicted" ? "终端已在另一处打开" : "连接已断开"}</span>
          {status === "closed" && (
            <button
              type="button"
              onClick={reconnect}
              className="rounded-lg border border-slate-600 px-3 py-1 text-slate-200 hover:bg-slate-700"
            >
              点击重连
            </button>
          )}
        </div>
      )}
      {/* 底边拖拽条:调面板高度 */}
      <div
        onPointerDown={(e) => {
          e.preventDefault()
          drag.current = { py: e.clientY, h: height }
        }}
        aria-label="调整终端高度"
        className="h-1.5 shrink-0 cursor-ns-resize bg-[#16161e] transition-colors hover:bg-slate-600"
      />
    </div>,
    document.body,
  )
}
