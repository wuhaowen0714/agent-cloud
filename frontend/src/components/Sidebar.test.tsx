import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { useStore } from "../store"
import { Sidebar } from "./Sidebar"

vi.mock("../api/client", () => ({
  api: {
    listAgents: vi.fn().mockResolvedValue([]),
    listSessions: vi.fn().mockResolvedValue([]),
    createAgent: vi.fn(),
    createSession: vi.fn(),
    logout: vi.fn().mockResolvedValue(undefined),
  },
}))

const A1 = {
  id: "a1",
  user_id: "u1",
  name: "main",
  model: "m",
  provider: "p",
  thinking_level: null,
  enabled_tools: [],
  permissions: {},
  key_ref: null,
}
// 正午锚点构造"N 个本地日前":离日界 12h,任何运行时刻判定稳定
const day = (n: number) => {
  const d = new Date()
  d.setDate(d.getDate() - n)
  d.setHours(12, 0, 0, 0)
  return d.toISOString()
}
const sess = (id: string, n: number) => ({
  id,
  user_id: "u1",
  agent_config_id: "a1",
  title: null,
  work_subdir: "workspace",
  last_active_at: day(n),
  last_context_tokens: null,
})

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

describe("Sidebar", () => {
  beforeEach(() => {
    vi.mocked(api.listAgents).mockResolvedValue([])
    vi.mocked(api.listSessions).mockResolvedValue([])
    useStore.setState({
      user: { id: "u1", email: "alice@example.com" },
      userId: "u1",
      agentId: null,
      sessionId: null,
    })
  })

  it("rail + 新对话(无 agent 禁用);邮箱只在账户菜单里", () => {
    render(wrap(<Sidebar />))
    expect(screen.getByRole("button", { name: "新对话" })).toBeDisabled()
    expect(screen.queryByText("alice@example.com")).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "账户" }))
    expect(screen.getByText("alice@example.com")).toBeInTheDocument()
  })

  it("自动落位:agents 就绪选第一个,再选其【最近活跃】会话", async () => {
    vi.mocked(api.listAgents).mockResolvedValue([A1] as never)
    // 最近活跃的放数组【前面】:旧实现取数组末尾会选错(s-old),按 last_active_at 才选对
    vi.mocked(api.listSessions).mockResolvedValue([sess("s-new", 0), sess("s-old", 3)] as never)
    render(wrap(<Sidebar />))
    await waitFor(() => expect(useStore.getState().agentId).toBe("a1"))
    await waitFor(() => expect(useStore.getState().sessionId).toBe("s-new")) // 非数组末尾
  })

  it("自愈:残留 agentId 指向已删 agent → 落回第一个", async () => {
    vi.mocked(api.listAgents).mockResolvedValue([A1] as never)
    useStore.setState({ agentId: "ghost-deleted", sessionId: null })
    render(wrap(<Sidebar />))
    await waitFor(() => expect(useStore.getState().agentId).toBe("a1"))
  })

  it("无任何 agent:面板空态指向 rail 新建", async () => {
    render(wrap(<Sidebar />))
    expect(await screen.findByText(/新建一个 Agent/)).toBeInTheDocument()
  })
})
