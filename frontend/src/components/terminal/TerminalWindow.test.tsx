import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { useStore } from "../../store"

// xterm 是真实 DOM/canvas 重组件,jsdom 跑不动 → mock 成最小桩
vi.mock("@xterm/xterm", () => ({
  Terminal: class {
    rows = 24
    cols = 80
    loadAddon() {}
    open() {}
    focus() {}
    write() {}
    onData() {
      return { dispose() {} }
    }
    dispose() {}
  },
}))
vi.mock("@xterm/addon-fit", () => ({
  FitAddon: class {
    fit() {}
  },
}))
vi.mock("@xterm/xterm/css/xterm.css", () => ({}))

class FakeWS {
  static OPEN = 1
  readyState = 1
  binaryType = ""
  onopen: (() => void) | null = null
  onmessage: ((e: unknown) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  sent: unknown[] = []
  url: string
  protocols?: string[]
  constructor(url: string, protocols?: string[]) {
    this.url = url
    this.protocols = protocols
  }
  send(d: unknown) {
    this.sent.push(d)
  }
  close() {
    this.onclose?.()
  }
}

import { TerminalWindow } from "./TerminalWindow"

beforeEach(() => {
  vi.stubGlobal("WebSocket", FakeWS as unknown as typeof WebSocket)
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  )
  localStorage.clear()
  useStore.setState({ terminalOpen: true })
})

afterEach(() => {
  vi.unstubAllGlobals()
  useStore.setState({ terminalOpen: false })
})

describe("TerminalWindow", () => {
  it("渲染悬浮终端窗口(标题 + 关闭按钮)", () => {
    render(<TerminalWindow />)
    expect(screen.getByRole("dialog", { name: "终端" })).toBeInTheDocument()
    expect(screen.getByLabelText("关闭终端")).toBeInTheDocument()
  })

  it("点关闭按钮 toggle terminalOpen", () => {
    render(<TerminalWindow />)
    fireEvent.click(screen.getByLabelText("关闭终端"))
    expect(useStore.getState().terminalOpen).toBe(false)
  })

  it("Esc 关闭", () => {
    render(<TerminalWindow />)
    fireEvent.keyDown(document, { key: "Escape" })
    expect(useStore.getState().terminalOpen).toBe(false)
  })

  it("有 resize 手柄", () => {
    render(<TerminalWindow />)
    expect(screen.getByLabelText("调整终端大小")).toBeInTheDocument()
  })
})
