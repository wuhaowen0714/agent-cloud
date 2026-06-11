import { FitAddon } from "@xterm/addon-fit"
import { Terminal } from "@xterm/xterm"
import { useEffect, useRef, useState } from "react"
import { getAccess } from "../../api/auth"

export type TermStatus = "connecting" | "open" | "closed"

// 终端 WS URL:同源 /api/terminal(vite 代理 ws→backend;生产同源 nginx 透传)。
function wsURL(): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:"
  return `${proto}//${location.host}/api/terminal`
}

/**
 * 把一个 xterm 实例接到后端终端 WS。
 * - 二进制下行 = PTY 输出 → term.write;term.onData → 二进制上行(键盘)
 * - fit 后把 rows/cols 作为文本 JSON 上行(resize 帧)
 * - 鉴权:token 走 subprotocol ["bearer", <access>](浏览器 WS 不能带 header)
 * 返回 { status, reconnect },窗口据此显示断开/重连 UX。
 */
export function useTerminalSocket(containerRef: React.RefObject<HTMLDivElement | null>) {
  const [status, setStatus] = useState<TermStatus>("connecting")
  const [attempt, setAttempt] = useState(0) // bump 触发重连
  const termRef = useRef<Terminal | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: 'Menlo, Monaco, "Courier New", monospace',
      theme: { background: "#1a1b26", foreground: "#c0caf5" },
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(container)
    fit.fit()
    termRef.current = term
    fitRef.current = fit

    setStatus("connecting")
    const ws = new WebSocket(wsURL(), ["bearer", getAccess() ?? ""])
    ws.binaryType = "arraybuffer"
    wsRef.current = ws

    const sendResize = () => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ rows: term.rows, cols: term.cols }))
      }
    }
    ws.onopen = () => {
      setStatus("open")
      fit.fit()
      sendResize()
      term.focus()
    }
    ws.onmessage = (e) => {
      if (e.data instanceof ArrayBuffer) term.write(new Uint8Array(e.data))
    }
    ws.onclose = () => setStatus("closed")
    ws.onerror = () => setStatus("closed")

    const dataDisp = term.onData((d) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(d))
    })
    // 容器尺寸变化(悬浮窗 resize/拖动)→ 重算 fit 并上报 PTY
    const ro = new ResizeObserver(() => {
      fit.fit()
      sendResize()
    })
    ro.observe(container)

    return () => {
      ro.disconnect()
      dataDisp.dispose()
      ws.close()
      term.dispose()
      termRef.current = null
      fitRef.current = null
      wsRef.current = null
    }
  }, [containerRef, attempt])

  return { status, reconnect: () => setAttempt((n) => n + 1) }
}
