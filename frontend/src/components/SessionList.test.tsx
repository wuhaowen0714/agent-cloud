import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { useStore } from "../store"
import { SessionList } from "./SessionList"

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
  title: "标题一",
  work_subdir: "workspace",
  last_context_tokens: null,
}

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

beforeEach(() => {
  useStore.setState({ userId: "u1", agentId: "a1", sessionId: "s1" })
  vi.spyOn(api, "listAgents").mockResolvedValue([A1] as never)
  vi.spyOn(api, "listSessions").mockResolvedValue([S1] as never)
})
afterEach(() => {
  useStore.setState({ userId: null, agentId: null, sessionId: null })
  vi.restoreAllMocks()
})

describe("SessionList", () => {
  it("重命名:菜单 → input → Enter 调 patchSession", async () => {
    const patch = vi.spyOn(api, "patchSession").mockResolvedValue(S1 as never)
    render(wrap(<SessionList />))
    await screen.findByText("标题一")
    fireEvent.click(screen.getByRole("button", { name: "标题一 更多操作" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "重命名" }))
    const input = await screen.findByDisplayValue("标题一")
    fireEvent.change(input, { target: { value: "新标题" } })
    fireEvent.keyDown(input, { key: "Enter" })
    await waitFor(() => expect(patch).toHaveBeenCalledWith("s1", { title: "新标题" }))
  })

  it("删除两次点击调 deleteSession,清掉当前选中", async () => {
    const del = vi.spyOn(api, "deleteSession").mockResolvedValue(undefined)
    render(wrap(<SessionList />))
    await screen.findByText("标题一")
    fireEvent.click(screen.getByRole("button", { name: "标题一 更多操作" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "删除" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "确认删除?" }))
    await waitFor(() => expect(del).toHaveBeenCalledWith("s1"))
    await waitFor(() => expect(useStore.getState().sessionId).toBeNull())
  })
})
