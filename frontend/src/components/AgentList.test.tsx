import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { useStore } from "../store"
import { AgentList } from "./AgentList"

const A1 = {
  id: "a1",
  user_id: "u1",
  name: "main",
  model: "DeepSeek-V4-Pro",
  provider: "openai",
  thinking_level: null,
  enabled_tools: [],
  permissions: {},
  key_ref: null,
}

let agents: (typeof A1)[]
const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

beforeEach(() => {
  agents = [A1]
  useStore.setState({ userId: "u1", agentId: "a1", sessionId: null })
  vi.spyOn(api, "listAgents").mockImplementation(() => Promise.resolve([...agents] as never))
})
afterEach(() => {
  useStore.setState({ userId: null, agentId: null })
  vi.restoreAllMocks()
})

describe("AgentList 一键新建", () => {
  it("默认名/默认模型直创,成功后选中并进入改名态;Enter 提交改名", async () => {
    const created = { ...A1, id: "a9", name: "Agent 1" }
    vi.spyOn(api, "createAgent").mockImplementation(() => {
      agents = [...agents, created]
      return Promise.resolve(created as never)
    })
    const patch = vi.spyOn(api, "patchAgent").mockResolvedValue(created as never)
    render(wrap(<AgentList />))
    fireEvent.click(await screen.findByRole("button", { name: "新建 Agent" }))
    await waitFor(() =>
      expect(api.createAgent).toHaveBeenCalledWith({
        name: "Agent 1",
        model: "DeepSeek-V4-Pro",
        provider: "openai",
      }),
    )
    const input = await screen.findByDisplayValue("Agent 1") // 改名态
    expect(useStore.getState().agentId).toBe("a9")
    fireEvent.change(input, { target: { value: "我的 Agent" } })
    fireEvent.keyDown(input, { key: "Enter" })
    await waitFor(() => expect(patch).toHaveBeenCalledWith("a9", { name: "我的 Agent" }))
  })
})

describe("AgentList 菜单", () => {
  it("重命名菜单项进入改名态", async () => {
    render(wrap(<AgentList />))
    await screen.findByText("main")
    fireEvent.click(screen.getByRole("button", { name: "main 更多操作" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "重命名" }))
    expect(await screen.findByDisplayValue("main")).toBeInTheDocument()
  })

  it("删除两次点击,删当前选中则落位到剩余第一个", async () => {
    const A2 = { ...A1, id: "a2", name: "second" }
    agents = [A1, A2]
    const del = vi.spyOn(api, "deleteAgent").mockImplementation(() => {
      agents = agents.filter((a) => a.id !== "a1")
      return Promise.resolve()
    })
    render(wrap(<AgentList />))
    await screen.findByText("main")
    fireEvent.click(screen.getByRole("button", { name: "main 更多操作" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "删除" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "连同全部会话删除?" }))
    await waitFor(() => expect(del).toHaveBeenCalledWith("a1"))
    await waitFor(() => expect(useStore.getState().agentId).toBe("a2"))
  })
})
