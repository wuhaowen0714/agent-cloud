import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
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
    const newChat = screen.getByRole("button", { name: "新对话" })
    expect(newChat).toBeDisabled()
    expect(screen.getByText("alice@example.com")).toBeInTheDocument()
  })

  it("自动落位:agents 就绪自动选第一个,再选其最近会话", async () => {
    vi.mocked(api.listAgents).mockResolvedValue([
      {
        id: "a1",
        user_id: "u1",
        name: "main",
        model: "m",
        provider: "p",
        thinking_level: null,
        enabled_tools: [],
        permissions: {},
        key_ref: null,
      },
    ] as never)
    vi.mocked(api.listSessions).mockResolvedValue([
      {
        id: "s1",
        user_id: "u1",
        agent_config_id: "a1",
        title: null,
        work_subdir: "workspace",
        last_context_tokens: null,
      },
    ] as never)
    useStore.setState({
      user: { id: "u1", email: "alice@example.com" },
      userId: "u1",
      agentId: null,
      sessionId: null,
    })
    render(wrap(<Sidebar />))
    await waitFor(() => expect(useStore.getState().agentId).toBe("a1"))
    await waitFor(() => expect(useStore.getState().sessionId).toBe("s1"))
  })
})
