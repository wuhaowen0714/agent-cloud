import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { useStore } from "../store"
import type { Message } from "../types"
import { MessageList } from "./MessageList"

afterEach(() => {
  useStore.setState({ live: null, sessionId: null, compactions: {} })
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

  it("当前会话正在压缩 → 隐藏重试(压缩与回合同锁,重试会撞 409)", () => {
    setErrorLive(true)
    useStore.setState({ sessionId: "s1", compactions: { s1: { phase: "running" } } })
    render(<MessageList messages={[]} onRetry={() => {}} />)
    expect(screen.queryByText("重试")).not.toBeInTheDocument()
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

  const containerOf = (c: HTMLElement) =>
    c.querySelector("[data-scroll-container]") as HTMLElement
  const geom = (
    el: HTMLElement,
    { scrollTop, scrollHeight = 1000 }: { scrollTop: number; scrollHeight?: number },
  ) => {
    Object.defineProperty(el, "scrollHeight", { configurable: true, value: scrollHeight })
    Object.defineProperty(el, "clientHeight", { configurable: true, value: 400 })
    Object.defineProperty(el, "scrollTop", {
      configurable: true, writable: true, value: scrollTop,
    })
  }

  const liveTurn = (text: string, startedAt = "2026-06-11T10:00:00") => ({
    userText: text, sessionId: "s1", startedAt,
    blocks: [], status: "streaming" as const,
  })

  it("在底部:live 更新自动滚动", () => {
    const { container, rerender } = render(<MessageList messages={[]} />)
    scrollSpy.mockClear() // 排除 mount 首滚,否则是空断言(审查 L1)
    const el = containerOf(container)
    geom(el, { scrollTop: 600 })
    fireEvent.scroll(el)
    useStore.setState({ live: liveTurn("问") })
    rerender(<MessageList messages={[]} />)
    expect(scrollSpy).toHaveBeenCalled()
  })

  it("上翻(scrollTop 下降)后:不再拽回,浮钮出现;点钮回底且钮消失", () => {
    useStore.setState({ live: liveTurn("问") })
    const { container, rerender } = render(<MessageList messages={[]} />)
    const el = containerOf(container)
    geom(el, { scrollTop: 600 })
    fireEvent.scroll(el) // 在底(记录 lastTop)
    geom(el, { scrollTop: 100 })
    fireEvent.scroll(el) // 上翻:scrollTop 下降且不在底 → 停跟随
    scrollSpy.mockClear()
    useStore.setState({ live: { ...liveTurn("问"), blocks: [] } })
    rerender(<MessageList messages={[]} />)
    expect(scrollSpy).not.toHaveBeenCalled()
    const btn = screen.getByRole("button", { name: "回到底部" })
    fireEvent.click(btn)
    expect(scrollSpy).toHaveBeenCalled()
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument()
  })

  it("内容增长把距底推远但 scrollTop 未降(程序滚动的异步事件):跟随不熄火(审查 H1)", () => {
    useStore.setState({ live: liveTurn("问") })
    const { container, rerender } = render(<MessageList messages={[]} />)
    const el = containerOf(container)
    geom(el, { scrollTop: 600 })
    fireEvent.scroll(el) // 在底,跟随中
    geom(el, { scrollTop: 600, scrollHeight: 2000 })
    fireEvent.scroll(el) // 内容撑高:距底 1000 但 scrollTop 未降 —— 不是用户行为
    scrollSpy.mockClear()
    useStore.setState({ live: { ...liveTurn("问"), blocks: [] } })
    rerender(<MessageList messages={[]} />)
    expect(scrollSpy).toHaveBeenCalled() // 仍在跟随
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument()
  })

  it("发送新消息强制回底:live 由空 → 带 userText", () => {
    useStore.setState({ live: null })
    const { container, rerender } = render(<MessageList messages={[]} />)
    const el = containerOf(container)
    geom(el, { scrollTop: 600 })
    fireEvent.scroll(el)
    geom(el, { scrollTop: 100 })
    fireEvent.scroll(el) // 上翻
    scrollSpy.mockClear()
    useStore.setState({ live: liveTurn("新问题") })
    rerender(<MessageList messages={[]} />)
    expect(scrollSpy).toHaveBeenCalled()
  })

  it("错误回合后直接再发送(live 非空→非空,startedAt 变):强制回底(审查 M1)", () => {
    useStore.setState({
      live: { ...liveTurn("旧问", "2026-06-11T09:00:00"), status: "error" as const },
    })
    const { container, rerender } = render(<MessageList messages={[]} />)
    const el = containerOf(container)
    geom(el, { scrollTop: 600 })
    fireEvent.scroll(el)
    geom(el, { scrollTop: 100 })
    fireEvent.scroll(el) // 上翻重读上文
    scrollSpy.mockClear()
    useStore.setState({ live: liveTurn("新问", "2026-06-11T10:30:00") }) // startLive 刷新 startedAt
    rerender(<MessageList messages={[]} />)
    expect(scrollSpy).toHaveBeenCalled()
  })
})
