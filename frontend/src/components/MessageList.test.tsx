import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { useStore } from "../store"
import type { Message } from "../types"
import { MessageList } from "./MessageList"

afterEach(() => {
  useStore.setState({ live: null })
})

function setErrorLive(recoverable?: boolean) {
  useStore.setState({
    live: {
      userText: "hi",
      sessionId: "s1",
      startedAt: "2026-06-10T09:00:00",
      blocks: [],
      status: "error",
      errorMessage: "the turn was interrupted, please retry",
      recoverable,
    },
  })
}

describe("MessageList error recovery", () => {
  it("recoverable error → shows a 重试 button that calls onRetry", () => {
    const onRetry = vi.fn()
    setErrorLive(true)
    render(<MessageList messages={[]} onRetry={onRetry} />)
    fireEvent.click(screen.getByText("重试"))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it("non-recoverable error → no 重试 button, guides to a new session", () => {
    setErrorLive(false)
    render(<MessageList messages={[]} onRetry={() => {}} />)
    expect(screen.queryByText("重试")).not.toBeInTheDocument()
    expect(screen.getByText(/开新会话/)).toBeInTheDocument()
  })
})

const msg = (over: Partial<Message>): Message => ({
  id: "m", seq: 0, role: "user",
  content: { text: "你好", tool_calls: [], tool_results: [] },
  created_at: "2026-06-10T14:32:00", ...over,
})

describe("MessageList 时间戳", () => {
  it("历史回合:提问与回答下方显示时间(断言时分,格式档位与运行日期无关)", () => {
    const messages: Message[] = [
      msg({ id: "u1", seq: 0 }),
      msg({
        id: "a1", seq: 1, role: "assistant",
        content: { text: "答案", tool_calls: [], tool_results: [] },
        created_at: "2026-06-10T14:35:00",
      }),
    ]
    render(<MessageList messages={messages} />)
    expect(screen.getByText(/14:32/)).toBeInTheDocument()
    expect(screen.getByText(/14:35/)).toBeInTheDocument()
  })

  it("live 流式:用户气泡下显示发送时间,助手侧无时间", () => {
    useStore.setState({
      live: { userText: "问", sessionId: "s1", blocks: [], status: "streaming", startedAt: "2026-06-10T09:05:00" },
    })
    render(<MessageList messages={[]} />)
    expect(screen.getByText(/09:05/)).toBeInTheDocument()
    expect(screen.getAllByText(/\d{2}:\d{2}/)).toHaveLength(1)
  })
})

describe("MessageList 粘底跟随", () => {
  const scrollSpy = vi.fn()

  beforeEach(() => {
    scrollSpy.mockClear()
    Element.prototype.scrollIntoView = scrollSpy
  })

  // 把滚动容器(role=log 外层 overflow-auto div)的几何设为「在底/上翻」
  const setGeometry = (container: HTMLElement, { away }: { away: boolean }) => {
    const el = container.querySelector("[data-scroll-container]") as HTMLElement
    Object.defineProperty(el, "scrollHeight", { configurable: true, value: 1000 })
    Object.defineProperty(el, "clientHeight", { configurable: true, value: 400 })
    Object.defineProperty(el, "scrollTop", {
      configurable: true, writable: true, value: away ? 100 : 600,
    })
    return el
  }

  const liveTurn = (text: string) => ({
    userText: text, sessionId: "s1", startedAt: "2026-06-11T10:00:00",
    blocks: [], status: "streaming" as const,
  })

  it("在底部:live 更新自动滚动", () => {
    const { container, rerender } = render(<MessageList messages={[]} />)
    setGeometry(container, { away: false })
    useStore.setState({ live: liveTurn("问") })
    rerender(<MessageList messages={[]} />)
    expect(scrollSpy).toHaveBeenCalled()
  })

  it("上翻后:live 更新不再拽回底部,出现「回到底部」钮;点击回底", () => {
    useStore.setState({ live: liveTurn("问") })
    const { container, rerender } = render(<MessageList messages={[]} />)
    const el = setGeometry(container, { away: true })
    fireEvent.scroll(el) // 上翻:跟随停止
    scrollSpy.mockClear()
    useStore.setState({ live: { ...liveTurn("问"), blocks: [] } })
    rerender(<MessageList messages={[]} />)
    expect(scrollSpy).not.toHaveBeenCalled()
    const btn = screen.getByRole("button", { name: "回到底部" })
    fireEvent.click(btn)
    expect(scrollSpy).toHaveBeenCalled()
  })

  it("发送新消息强制回底:即使此前上翻", () => {
    useStore.setState({ live: null })
    const { container, rerender } = render(<MessageList messages={[]} />)
    const el = setGeometry(container, { away: true })
    fireEvent.scroll(el) // 上翻
    scrollSpy.mockClear()
    useStore.setState({ live: liveTurn("新问题") }) // null → 带 userText = 用户发送
    rerender(<MessageList messages={[]} />)
    expect(scrollSpy).toHaveBeenCalled()
  })
})
