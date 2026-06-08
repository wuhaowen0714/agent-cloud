import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { useStore } from "../store"
import { MessageList } from "./MessageList"

afterEach(() => {
  useStore.setState({ live: null })
})

function setErrorLive(recoverable?: boolean) {
  useStore.setState({
    live: {
      userText: "hi",
      sessionId: "s1",
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
