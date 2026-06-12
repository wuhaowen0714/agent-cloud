import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../../api/client"
import { useStore } from "../../store"
import { AgentSettings } from "./AgentSettings"

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

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

// 编辑态渲染所需的最小 mock 集(含 MemoryPanel 的 getMemory,防 jsdom 真网络)
const mockEditor = () => {
  useStore.setState({ userId: "u1", agentId: "a1" })
  vi.spyOn(api, "listAgents").mockResolvedValue([A1] as never)
  vi.spyOn(api, "listDocs").mockResolvedValue([])
  vi.spyOn(api, "listCredentials").mockResolvedValue([])
  vi.spyOn(api, "getMemory").mockResolvedValue({
    scope: "agent",
    owner_id: "a1",
    content: "",
    version: 0,
  })
}

describe("AgentSettings", () => {
  beforeEach(() => useStore.setState({ userId: "u1", agentId: null }))
  afterEach(() => vi.restoreAllMocks())

  // 创建职责已移到侧栏 AgentRail(一键直创,见 AgentRail.test);设置页只编辑。
  it("无选中 agent 时显示空态提示", () => {
    render(wrap(<AgentSettings />))
    expect(screen.getByText("在左侧选择或新建一个 agent")).toBeInTheDocument()
  })

  // 工具/技能开关已收敛到顶栏弹层(即点即存);设置页若再保留快照式开关,
  // 保存会把打开抽屉时的旧 enabled_tools/技能集整个写回,覆盖弹层里的改动。
  it("编辑态不再渲染工具开关与启用技能组", async () => {
    mockEditor()
    render(wrap(<AgentSettings />))
    expect(await screen.findByText("基本")).toBeInTheDocument()
    expect(screen.queryByText("工具")).not.toBeInTheDocument()
    expect(screen.queryByText("启用技能")).not.toBeInTheDocument()
    expect(screen.queryByRole("switch")).not.toBeInTheDocument()
  })

  // 本次删除的核心契约:保存只写表单字段,不再携带 enabled_tools / 技能集快照
  // (否则会覆盖顶栏弹层里刚做的改动)。钉住 payload 防无 UI 的回归。
  it("保存只 PATCH 表单字段:payload 不含 enabled_tools,且不调 setAgentSkills", async () => {
    mockEditor()
    const patch = vi.spyOn(api, "patchAgent").mockResolvedValue(A1 as never)
    const setSkills = vi.spyOn(api, "setAgentSkills").mockResolvedValue([])
    render(wrap(<AgentSettings />))
    // MemoryPanel 也有「保存」;表单主保存在页脚(DOM 最后一个)
    const btn = (await screen.findAllByRole("button", { name: "保存" })).at(-1)!
    await waitFor(() => expect(btn).toBeEnabled()) // 表单初始化(草稿灌入)后才可保存
    fireEvent.click(btn)
    await waitFor(() => expect(patch).toHaveBeenCalled())
    expect("enabled_tools" in (patch.mock.calls[0][1] as object)).toBe(false)
    expect(setSkills).not.toHaveBeenCalled()
  })
})
