import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../../api/client"
import { useStore } from "../../store"
import { AgentSettings } from "./AgentSettings"

const wrap = (ui: ReactNode) => <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>

describe("AgentSettings", () => {
  beforeEach(() => useStore.setState({ userId: "u1", agentId: null }))
  afterEach(() => vi.restoreAllMocks())

  it("shows the create form when no agent is selected", () => {
    render(wrap(<AgentSettings />))
    expect(screen.getByText("新建 Agent")).toBeInTheDocument()
    expect(screen.getByText("创建")).toBeInTheDocument()
  })

  it("创建表单不填模型,提交带预设 DeepSeek-V4-Pro", async () => {
    const spy = vi.spyOn(api, "createAgent").mockResolvedValue({ id: "a9" } as never)
    // 创建成功后 setAgent("a9") 会挂载 AgentEditor,把它的查询都打空,免得测试输出报网络噪音
    vi.spyOn(api, "listAgents").mockResolvedValue([])
    vi.spyOn(api, "listDocs").mockResolvedValue([])
    vi.spyOn(api, "listSkills").mockResolvedValue([])
    vi.spyOn(api, "listCredentials").mockResolvedValue([])
    vi.spyOn(api, "getAgentSkills").mockResolvedValue([])
    vi.spyOn(api, "listModels").mockResolvedValue([])
    render(wrap(<AgentSettings />))
    expect(screen.queryByPlaceholderText(/model/i)).not.toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText("name"), { target: { value: "A1" } })
    fireEvent.click(screen.getByRole("button", { name: "创建" }))
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({
        name: "A1",
        provider: "openai",
        model: "DeepSeek-V4-Pro",
      }),
    )
  })
})
