import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../../api/client"
import { useStore } from "../../store"
import type { Skill } from "../../types"
import { SkillsPanel } from "./SkillsPanel"

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

const skill = (over: Partial<Skill>): Skill => ({
  id: "s1", user_id: "u1", name: "skill-creator", description: "内置",
  source: "registry", version: "1.0.0", ...over,
})

describe("SkillsPanel", () => {
  beforeEach(() => useStore.setState({ userId: "u1" }))
  afterEach(() => vi.restoreAllMocks())

  it("无安装界面;内置(registry)不可删,uploaded 可删", async () => {
    vi.spyOn(api, "listSkills").mockResolvedValue([
      skill({ id: "s1", name: "skill-creator", source: "registry" }),
      skill({ id: "s2", name: "zippy", source: "uploaded" }),
    ])
    render(wrap(<SkillsPanel />))
    await waitFor(() => expect(screen.getByText("skill-creator")).toBeInTheDocument())

    expect(screen.queryByText("从 registry 安装")).not.toBeInTheDocument()
    // 仅 uploaded 行有删除按钮(内置删了无入口装回,前端不暴露)
    expect(screen.getAllByRole("button", { name: "删除" })).toHaveLength(1)
    expect(screen.getByText("zippy")).toBeInTheDocument()
  })
})
