import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { useStore } from "../store"
import { TopBar } from "./TopBar"

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
const S1 = {
  id: "s1",
  user_id: "u1",
  agent_config_id: "a1",
  title: "重构登录页",
  work_subdir: "workspace",
  last_context_tokens: null,
}

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

beforeEach(() => {
  useStore.setState({ userId: "u1", agentId: "a1", sessionId: "s1", fileDrawerOpen: false })
  vi.spyOn(api, "listAgents").mockResolvedValue([A1] as never)
  vi.spyOn(api, "listSessions").mockResolvedValue([S1] as never)
})
afterEach(() => {
  useStore.setState({ userId: null, agentId: null, sessionId: null, fileDrawerOpen: false })
  vi.restoreAllMocks()
})

describe("TopBar", () => {
  it("面包屑显示 agent / 会话标题", async () => {
    render(wrap(<TopBar />))
    expect(await screen.findByText("main")).toBeInTheDocument()
    expect(await screen.findByText("重构登录页")).toBeInTheDocument()
  })

  it("无会话只显 agent 名", async () => {
    useStore.setState({ sessionId: null })
    render(wrap(<TopBar />))
    expect(await screen.findByText("main")).toBeInTheDocument()
    expect(screen.queryByText("重构登录页")).not.toBeInTheDocument()
  })

  it("点文件按钮翻转抽屉开关", () => {
    render(wrap(<TopBar />))
    fireEvent.click(screen.getByRole("button", { name: "工作区文件" }))
    expect(useStore.getState().fileDrawerOpen).toBe(true)
  })
})
