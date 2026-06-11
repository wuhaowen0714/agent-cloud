import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../../api/client"
import { useStore } from "../../store"
import { AgentSettings } from "./AgentSettings"

const wrap = (ui: ReactNode) => <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>

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

describe("AgentSettings", () => {
  beforeEach(() => useStore.setState({ userId: "u1", agentId: null }))
  afterEach(() => vi.restoreAllMocks())

  // 创建职责已移到侧栏 AgentList(一键直创,见 AgentList.test);设置页只编辑。
  it("无选中 agent 时显示空态提示", () => {
    render(wrap(<AgentSettings />))
    expect(screen.getByText("在左侧选择或新建一个 agent")).toBeInTheDocument()
  })

  // 工具/技能开关已收敛到顶栏弹层(即点即存);设置页若再保留快照式开关,
  // 保存会把打开抽屉时的旧 enabled_tools/技能集整个写回,覆盖弹层里的改动。
  it("编辑态不再渲染工具开关与启用技能组", async () => {
    useStore.setState({ userId: "u1", agentId: "a1" })
    vi.spyOn(api, "listAgents").mockResolvedValue([A1] as never)
    vi.spyOn(api, "listDocs").mockResolvedValue([])
    vi.spyOn(api, "listCredentials").mockResolvedValue([])
    vi.spyOn(api, "listSkills").mockResolvedValue([])
    vi.spyOn(api, "getAgentSkills").mockResolvedValue([])
    render(wrap(<AgentSettings />))
    expect(await screen.findByText("基本")).toBeInTheDocument()
    expect(screen.queryByText("工具")).not.toBeInTheDocument()
    expect(screen.queryByText("启用技能")).not.toBeInTheDocument()
    expect(screen.queryByRole("switch")).not.toBeInTheDocument()
  })
})
