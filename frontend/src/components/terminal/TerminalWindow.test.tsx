import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
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

// aria-hidden 元素算不出 accessible name,改按 role 属性直接取(避开 name 匹配)
const panel = () => document.querySelector('[role="dialog"]') as HTMLElement

describe("TerminalWindow(Ghostty 下拉面板)", () => {
  it("渲染下拉面板:标题 + 收起按钮 + 高度拖拽条", () => {
    render(<TerminalWindow />)
    expect(panel()).toBeInTheDocument()
    expect(screen.getByLabelText("收起终端")).toBeInTheDocument()
    expect(screen.getByLabelText("调整终端高度")).toBeInTheDocument()
  })

  it("展开态滑入(translate-y-0)", async () => {
    render(<TerminalWindow />)
    await waitFor(() => expect(panel().className).toContain("translate-y-0"))
  })

  it("收起 ≠ 卸载:terminalOpen=false 时仍在文档中,仅滑出(去掉展开态 translate-y-0)", async () => {
    render(<TerminalWindow />)
    await waitFor(() => expect(panel().className).toContain("translate-y-0"))
    act(() => useStore.setState({ terminalOpen: false }))
    // 收起:不再有展开态 translate-y-0,且有 pointer-events-none(具体位移类含 calc,不硬断言)
    await waitFor(() => expect(panel().className).not.toContain("translate-y-0"))
    expect(panel().className).toContain("pointer-events-none")
    expect(panel()).toBeInTheDocument() // 常驻挂载,WS/PTY/缓冲保留
    expect(panel().getAttribute("aria-hidden")).toBe("true")
  })

  it("点收起按钮 toggle terminalOpen", () => {
    render(<TerminalWindow />)
    fireEvent.click(screen.getByLabelText("收起终端"))
    expect(useStore.getState().terminalOpen).toBe(false)
  })

  it("Esc 收起;收起后再按 Esc 不会把面板弹回来", async () => {
    render(<TerminalWindow />)
    fireEvent.keyDown(document, { key: "Escape" })
    expect(useStore.getState().terminalOpen).toBe(false)
    await waitFor(() => expect(panel().className).not.toContain("translate-y-0"))
    fireEvent.keyDown(document, { key: "Escape" }) // 仅展开时监听,不应重新展开
    expect(useStore.getState().terminalOpen).toBe(false)
  })
})
