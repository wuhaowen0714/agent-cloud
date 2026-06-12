import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { useStore } from "../store"
import { AgentHeader } from "./AgentHeader"

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
const noAuto = { autoRenameId: null, onAutoRenameConsumed: () => {} }

beforeEach(() => {
  agents = [A1, { ...A1, id: "a2", name: "second" }]
  useStore.setState({ userId: "u1", agentId: "a1", sessionId: null })
  vi.spyOn(api, "listAgents").mockImplementation(() => Promise.resolve([...agents] as never))
})
afterEach(() => {
  useStore.setState({ userId: null, agentId: null, sessionId: null, settingsOpen: false })
  vi.restoreAllMocks()
})

describe("AgentHeader", () => {
  it("显示名字与模型;⚙ 打开 agent 设置", async () => {
    render(wrap(<AgentHeader {...noAuto} />))
    expect(await screen.findByText("main")).toBeInTheDocument()
    expect(screen.getByText("DeepSeek-V4-Pro")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "agent 设置" }))
    expect(useStore.getState().settingsOpen).toBe(true)
  })

  it("菜单重命名 → input → Enter 调 patchAgent;IME 回车不提交", async () => {
    const patch = vi.spyOn(api, "patchAgent").mockResolvedValue(A1 as never)
    render(wrap(<AgentHeader {...noAuto} />))
    await screen.findByText("main")
    fireEvent.click(screen.getByRole("button", { name: "main 更多操作" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "重命名" }))
    const input = await screen.findByDisplayValue("main")
    fireEvent.change(input, { target: { value: "我的" } })
    fireEvent.keyDown(input, { key: "Enter", isComposing: true }) // 选字回车
    expect(patch).not.toHaveBeenCalled()
    fireEvent.keyDown(input, { key: "Enter" })
    await waitFor(() => expect(patch).toHaveBeenCalledWith("a1", { name: "我的" }))
  })

  it("删除两次点击;删当前选中落位到剩余第一个", async () => {
    const del = vi.spyOn(api, "deleteAgent").mockImplementation(() => {
      agents = agents.filter((a) => a.id !== "a1")
      return Promise.resolve()
    })
    render(wrap(<AgentHeader {...noAuto} />))
    await screen.findByText("main")
    fireEvent.click(screen.getByRole("button", { name: "main 更多操作" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "删除" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "连同全部会话删除?" }))
    await waitFor(() => expect(del).toHaveBeenCalledWith("a1"))
    await waitFor(() => expect(useStore.getState().agentId).toBe("a2"))
  })

  it("autoRenameId 命中当前 agent → 直接进入改名态并消费", async () => {
    const consumed = vi.fn()
    render(wrap(<AgentHeader autoRenameId="a1" onAutoRenameConsumed={consumed} />))
    expect(await screen.findByDisplayValue("main")).toBeInTheDocument()
    expect(consumed).toHaveBeenCalled()
  })
})
