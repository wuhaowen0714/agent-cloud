import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
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
