import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { BUILTIN_TOOLS } from "../../agentConfig"
import { api } from "../../api/client"
import { useStore } from "../../store"
import type { AgentConfig } from "../../types"
import { ToolsMenu } from "./ToolsMenu"

const agent = (enabled: string[]): AgentConfig => ({
  id: "a1", user_id: "u1", name: "main", model: "m", provider: "p",
  thinking_level: null, enabled_tools: enabled, permissions: {}, key_ref: null,
})

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

beforeEach(() => useStore.setState({ userId: "u1" }))
afterEach(() => vi.restoreAllMocks())

describe("ToolsMenu", () => {
  it("enabled_tools 为空 = 全部启用:所有开关全开", () => {
    render(wrap(<ToolsMenu agent={agent([])} />))
    const switches = screen.getAllByRole("switch")
    expect(switches).toHaveLength(BUILTIN_TOOLS.length)
    for (const s of switches) expect(s).toHaveAttribute("aria-checked", "true")
  })

  it("关掉一个工具:PATCH 其余工具(按内置顺序)", async () => {
    const patch = vi.spyOn(api, "patchAgent").mockResolvedValue(agent([]))
    render(wrap(<ToolsMenu agent={agent([])} />))
    fireEvent.click(screen.getByRole("switch", { name: "bash" }))
    // 动态算其余工具(按内置顺序),避免每次新增内置工具都要改硬编码列表
    const rest = BUILTIN_TOOLS.map((t) => t.name).filter((n) => n !== "bash")
    await waitFor(() => expect(patch).toHaveBeenCalledWith("a1", { enabled_tools: rest }))
  })

  it("把最后一个关闭的工具开回:规范化为 [](= 全部)", async () => {
    const patch = vi.spyOn(api, "patchAgent").mockResolvedValue(agent([]))
    // 启用「除最后一个外的全部」,开回最后一个 → 凑齐全部 → 规范化为 [](动态,免硬编码)
    const names = BUILTIN_TOOLS.map((t) => t.name)
    const last = names[names.length - 1]
    render(wrap(<ToolsMenu agent={agent(names.slice(0, -1))} />))
    fireEvent.click(screen.getByRole("switch", { name: last }))
    await waitFor(() => expect(patch).toHaveBeenCalledWith("a1", { enabled_tools: [] }))
  })

  it("最后一个启用的工具:开关禁用(空集会回退成「全部」语义,危险)", () => {
    const patch = vi.spyOn(api, "patchAgent").mockResolvedValue(agent([]))
    render(wrap(<ToolsMenu agent={agent(["bash"])} />))
    const sw = screen.getByRole("switch", { name: "bash" })
    expect(sw).toBeDisabled()
    fireEvent.click(sw)
    expect(patch).not.toHaveBeenCalled()
  })
})
