import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { useStore } from "../store"
import { AgentRail, agentColor, agentInitial } from "./AgentRail"

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
  agents = [A1, { ...A1, id: "a2", name: "Agent 2" }]
  useStore.setState({
    user: { id: "u1", email: "alice@e.com" },
    userId: "u1",
    agentId: "a1",
    sessionId: null,
  })
  vi.spyOn(api, "listAgents").mockImplementation(() => Promise.resolve([...agents] as never))
})
afterEach(() => {
  useStore.setState({ user: null, userId: null, agentId: null, sessionId: null })
  vi.restoreAllMocks()
})

describe("agentInitial / agentColor", () => {
  it("字母+数字名取两位,其余取首字符大写", () => {
    expect(agentInitial("Agent 1")).toBe("A1")
    expect(agentInitial("agent12")).toBe("A12")
    expect(agentInitial("hello")).toBe("H")
    expect(agentInitial("主力")).toBe("主")
    expect(agentInitial("🤖 bot")).toBe("🤖") // 代理对按码点取,不能劈成半个(审查 M-1)
    expect(agentInitial("  ")).toBe("?")
  })
  it("配色稳定且来自色板", () => {
    expect(agentColor("main")).toBe(agentColor("main"))
    expect(agentColor("main")).toMatch(/^bg-(teal|violet|sky|amber|rose|emerald)-100 text-\1-700$/)
  })
})

describe("AgentRail", () => {
  it("渲染头像缩写;点未选中头像切换;点已选中不重置", async () => {
    render(wrap(<AgentRail onCreated={() => {}} />))
    expect(await screen.findByRole("button", { name: "Agent 2" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Agent 2" }))
    expect(useStore.getState().agentId).toBe("a2")
    act(() => {
      useStore.setState({ agentId: "a1", sessionId: "keep" }) // act:让组件拿到新 agentId 再点
    })
    fireEvent.click(screen.getByRole("button", { name: "main" }))
    expect(useStore.getState().sessionId).toBe("keep") // setAgent 未被调(它会清 sessionId)
  })

  it("hover 头像弹「名字 · 模型」tooltip(portal 到 body),移出消失", async () => {
    render(wrap(<AgentRail onCreated={() => {}} />))
    fireEvent.mouseEnter(await screen.findByRole("button", { name: "main" }))
    expect(await screen.findByText("main · DeepSeek-V4-Pro")).toBeInTheDocument()
    fireEvent.mouseLeave(screen.getByRole("button", { name: "main" }))
    expect(screen.queryByText("main · DeepSeek-V4-Pro")).not.toBeInTheDocument()
  })

  it("+ 新建:默认名直创,成功选中并回调 onCreated", async () => {
    const created = { ...A1, id: "a9", name: "Agent 3" }
    vi.spyOn(api, "createAgent").mockImplementation(() => {
      agents = [...agents, created]
      return Promise.resolve(created as never)
    })
    const onCreated = vi.fn()
    render(wrap(<AgentRail onCreated={onCreated} />))
    await screen.findByRole("button", { name: "Agent 2" }) // 等名单加载,默认名才算得对
    fireEvent.click(screen.getByRole("button", { name: "新建 Agent" }))
    await waitFor(() =>
      expect(api.createAgent).toHaveBeenCalledWith({
        name: "Agent 3",
        model: "DeepSeek-V4-Pro",
        provider: "openai",
      }),
    )
    await waitFor(() => expect(useStore.getState().agentId).toBe("a9"))
    expect(onCreated).toHaveBeenCalledWith("a9")
  })
})
