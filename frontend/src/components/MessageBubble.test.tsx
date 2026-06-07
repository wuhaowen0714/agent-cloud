import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import type { Message } from "../types"
import { MessageBubble } from "./MessageBubble"

const mk = (over: Partial<Message>): Message => ({
  id: "m", seq: 0, role: "assistant",
  content: { text: "", tool_calls: [], tool_results: [] }, ...over,
})

describe("MessageBubble", () => {
  it("renders user text", () => {
    render(<MessageBubble message={mk({ role: "user", content: { text: "hello", tool_calls: [], tool_results: [] } })} />)
    expect(screen.getByText("hello")).toBeInTheDocument()
  })

  it("renders assistant tool call", () => {
    render(<MessageBubble message={mk({ content: { text: "ok", tool_calls: [{ id: "c1", name: "bash", arguments: { command: "ls" } }], tool_results: [] } })} />)
    expect(screen.getByText(/bash/)).toBeInTheDocument()
  })

  it("marks errored tool result", () => {
    render(<MessageBubble message={mk({ role: "tool", content: { text: "", tool_calls: [], tool_results: [{ call_id: "c1", content: "boom", is_error: true }] } })} />)
    expect(screen.getByText(/\[error\]/)).toBeInTheDocument()
  })
})
