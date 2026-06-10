import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
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
  it("enabled_tools 为空 = 全部启用:5 个开关全开", () => {
    render(wrap(<ToolsMenu agent={agent([])} />))
    const switches = screen.getAllByRole("switch")
    expect(switches).toHaveLength(5)
    for (const s of switches) expect(s).toHaveAttribute("aria-checked", "true")
  })

  it("关掉一个工具:PATCH 其余 4 个(按内置顺序)", async () => {
    const patch = vi.spyOn(api, "patchAgent").mockResolvedValue(agent([]))
    render(wrap(<ToolsMenu agent={agent([])} />))
    fireEvent.click(screen.getByRole("switch", { name: "bash" }))
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("a1", {
        enabled_tools: ["write_file", "read_file", "edit", "remember"],
      }),
    )
  })

  it("把最后一个关闭的工具开回:规范化为 [](= 全部)", async () => {
    const patch = vi.spyOn(api, "patchAgent").mockResolvedValue(agent([]))
    render(wrap(<ToolsMenu agent={agent(["bash", "write_file", "read_file", "edit"])} />))
    fireEvent.click(screen.getByRole("switch", { name: "remember" }))
    await waitFor(() => expect(patch).toHaveBeenCalledWith("a1", { enabled_tools: [] }))
  })

  it("关掉仅剩的一个工具被忽略(空集会回退成「全部」语义,危险)", () => {
    const patch = vi.spyOn(api, "patchAgent").mockResolvedValue(agent([]))
    render(wrap(<ToolsMenu agent={agent(["bash"])} />))
    fireEvent.click(screen.getByRole("switch", { name: "bash" }))
    expect(patch).not.toHaveBeenCalled()
  })
})
