import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { useStore } from "../store"
import { Sidebar } from "./Sidebar"

vi.mock("../api/client", () => ({
  api: {
    listAgents: vi.fn().mockResolvedValue([]),
    listSessions: vi.fn().mockResolvedValue([]),
  },
}))

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

describe("Sidebar", () => {
  beforeEach(() => {
    useStore.setState({ user: { id: "u1", email: "alice@example.com" }, userId: "u1", agentId: null })
  })

  it("renders brand, the new-chat button (disabled without an agent), and the account email", () => {
    render(wrap(<Sidebar />))
    expect(screen.getByText("Agent Cloud")).toBeInTheDocument()
    const newChat = screen.getByRole("button", { name: "＋ 新对话" })
    expect(newChat).toBeDisabled()
    expect(screen.getByText("alice@example.com")).toBeInTheDocument()
  })
})
