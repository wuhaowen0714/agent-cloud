import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../../api/client"
import { useStore } from "../../store"
import type { Skill } from "../../types"
import { SkillsMenu } from "./SkillsMenu"

const skill = (over: Partial<Skill>): Skill => ({
  id: "s1", user_id: "u1", name: "skill-creator", description: "内置",
  source: "registry", version: "1.0.0", ...over,
})

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

beforeEach(() => {
  useStore.setState({ userId: "u1" })
  vi.spyOn(api, "listSkills").mockResolvedValue([
    skill({ id: "s1", name: "skill-creator" }),
    skill({ id: "s2", name: "zippy", source: "uploaded" }),
  ])
})
afterEach(() => vi.restoreAllMocks())

describe("SkillsMenu", () => {
  it("列出全部技能,checked = agent 启用集", async () => {
    vi.spyOn(api, "getAgentSkills").mockResolvedValue([skill({ id: "s1" })])
    render(wrap(<SkillsMenu agentId="a1" />))
    await waitFor(() =>
      expect(screen.getByRole("switch", { name: "skill-creator" })).toHaveAttribute(
        "aria-checked", "true",
      ),
    )
    expect(screen.getByRole("switch", { name: "zippy" })).toHaveAttribute("aria-checked", "false")
  })

  it("开启一个技能:PUT 新集合(含新旧)", async () => {
    vi.spyOn(api, "getAgentSkills").mockResolvedValue([skill({ id: "s1" })])
    const put = vi.spyOn(api, "setAgentSkills").mockResolvedValue([])
    render(wrap(<SkillsMenu agentId="a1" />))
    await screen.findByRole("switch", { name: "zippy" })
    fireEvent.click(screen.getByRole("switch", { name: "zippy" }))
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
    const [aid, ids] = put.mock.calls[0]
    expect(aid).toBe("a1")
    expect([...ids].sort()).toEqual(["s1", "s2"])
  })

  it("关闭一个技能:PUT 去掉它的集合", async () => {
    vi.spyOn(api, "getAgentSkills").mockResolvedValue([
      skill({ id: "s1" }), skill({ id: "s2", name: "zippy", source: "uploaded" }),
    ])
    const put = vi.spyOn(api, "setAgentSkills").mockResolvedValue([])
    render(wrap(<SkillsMenu agentId="a1" />))
    await screen.findByRole("switch", { name: "skill-creator" })
    fireEvent.click(screen.getByRole("switch", { name: "skill-creator" }))
    await waitFor(() => expect(put).toHaveBeenCalledWith("a1", ["s2"]))
  })

  it("技能池为空给空态", async () => {
    vi.mocked(api.listSkills).mockResolvedValue([])
    vi.spyOn(api, "getAgentSkills").mockResolvedValue([])
    render(wrap(<SkillsMenu agentId="a1" />))
    expect(await screen.findByText("技能池为空")).toBeInTheDocument()
  })

  it("内置技能展示中文描述(后端英文 description 不直接示人)", async () => {
    vi.mocked(api.listSkills).mockResolvedValue([
      skill({ id: "s1", name: "docx", description: "Use this skill whenever the user wants…" }),
    ])
    vi.spyOn(api, "getAgentSkills").mockResolvedValue([])
    render(wrap(<SkillsMenu agentId="a1" />))
    expect(await screen.findByText("创建、读取、编辑 Word 文档(.docx)")).toBeInTheDocument()
    expect(screen.queryByText("Use this skill whenever the user wants…")).toBeNull()
  })
})

describe("SkillsMenu 加载 gate(审查 M2)", () => {
  it("启用集未加载完不渲染开关——此时全『关』是假状态,点一下会清空真实启用集", async () => {
    vi.spyOn(api, "getAgentSkills").mockReturnValue(new Promise(() => {}) as never)
    render(wrap(<SkillsMenu agentId="a1" />))
    expect(await screen.findByText("加载中…")).toBeInTheDocument()
    expect(screen.queryAllByRole("switch")).toHaveLength(0)
  })
})
