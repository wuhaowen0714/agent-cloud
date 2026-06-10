import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it } from "vitest"
import { useStore } from "../../store"
import { AgentSettings } from "./AgentSettings"

const wrap = (ui: ReactNode) => <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>

describe("AgentSettings", () => {
  beforeEach(() => useStore.setState({ userId: "u1", agentId: null }))

  // 创建职责已移到侧栏 AgentList(一键直创,见 AgentList.test);设置页只编辑。
  it("无选中 agent 时显示空态提示", () => {
    render(wrap(<AgentSettings />))
    expect(screen.getByText("在左侧选择或新建一个 agent")).toBeInTheDocument()
  })
})
