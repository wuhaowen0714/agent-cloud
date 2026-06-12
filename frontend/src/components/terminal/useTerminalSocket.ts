import { FitAddon } from "@xterm/addon-fit"
import { Terminal } from "@xterm/xterm"
import { useCallback, useEffect, useRef, useState } from "react"
import { getAccess } from "../../api/auth"

export type TermStatus = "connecting" | "open" | "closed" | "evicted"

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
  // 主动关闭标记:cleanup / reconnect 关 ws 时置位,onclose 据此静默(不误报"已断开")。
  // 否则 React StrictMode(dev)双跑 effect 的 unmount→remount 会让被 cleanup 关掉的那个
  // 连接弹出断开浮层。
  const closingRef = useRef(false)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    closingRef.current = false
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
    // WS 建立延迟到下一 tick:React StrictMode(dev)双跑 effect 会 setup→cleanup→setup,
    // 同步建 WS 会先后开两个连接,后端单终端接管让它们互踢(活的那个反被踢成 evicted)。
    // 延迟后,第一次的 cleanup 会 clearTimeout 取消其建立,最终只建一个连接,无竞态。
    let ws: WebSocket | null = null
    const sendResize = () => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ rows: term.rows, cols: term.cols }))
      }
    }
    const wsTimer = setTimeout(() => {
      ws = new WebSocket(wsURL(), ["bearer", getAccess() ?? ""])
      ws.binaryType = "arraybuffer"
      wsRef.current = ws
      ws.onopen = () => {
        setStatus("open")
        fit.fit()
        sendResize()
        term.focus()
      }
      ws.onmessage = (e) => {
        if (e.data instanceof ArrayBuffer) term.write(new Uint8Array(e.data))
      }
      ws.onclose = (e) => {
        if (closingRef.current) return // 自己主动关(cleanup/reconnect)→ 静默
        // 4001 = 被另一处终端接管(后端单终端策略);其余为真断开。接管不提供重连(重连会
        // 再次被踢),只提示。
        setStatus(e.code === 4001 ? "evicted" : "closed")
      }
      ws.onerror = () => {
        if (!closingRef.current) setStatus("closed")
      }
    }, 0)

    const dataDisp = term.onData((d) => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(d))
    })
    // 容器尺寸变化(面板高度拖拽 / 视口变化)→ 重算 fit 并上报 PTY
    const ro = new ResizeObserver(() => {
      fit.fit()
      sendResize()
    })
    ro.observe(container)

    return () => {
      closingRef.current = true // 标记主动关,onclose 静默
      clearTimeout(wsTimer)
      ro.disconnect()
      dataDisp.dispose()
      ws?.close()
      term.dispose()
      termRef.current = null
      fitRef.current = null
      wsRef.current = null
    }
  }, [containerRef, attempt])

  // 稳定引用(进消费方 effect deps):下拉面板展开时重新聚焦 xterm(收起不销毁,焦点已移走)
  const focus = useCallback(() => termRef.current?.focus(), [])
  const reconnect = useCallback(() => setAttempt((n) => n + 1), [])
  return { status, reconnect, focus }
}
