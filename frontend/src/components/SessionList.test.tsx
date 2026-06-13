import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { useStore } from "../store"
import { SessionList } from "./SessionList"

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
const S1 = {
  id: "s1",
  user_id: "u1",
  agent_config_id: "a1",
  title: "标题一",
  work_subdir: "workspace",
  last_active_at: new Date().toISOString(),
  last_context_tokens: null,
}

// 正午锚点构造"N 个本地日前":离日界 12h,任何运行时刻分组判定都稳定
const day = (n: number) => {
  const d = new Date()
  d.setDate(d.getDate() - n)
  d.setHours(12, 0, 0, 0)
  return d.toISOString()
}

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

beforeEach(() => {
  useStore.setState({ userId: "u1", agentId: "a1", sessionId: "s1" })
  vi.spyOn(api, "listAgents").mockResolvedValue([A1] as never)
  vi.spyOn(api, "listSessions").mockResolvedValue([S1] as never)
})
afterEach(() => {
  useStore.setState({ userId: null, agentId: null, sessionId: null })
  vi.restoreAllMocks()
})

describe("SessionList", () => {
  it("按 last_active_at 降序 + 时间分组标签;区头已删", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue([
      { ...S1, id: "old", title: "旧会话", last_active_at: day(40) },
      { ...S1, id: "yesterday", title: "昨日会话", last_active_at: day(1) },
      { ...S1, id: "now", title: "刚刚会话", last_active_at: day(0) },
    ] as never)
    render(wrap(<SessionList />))
    await screen.findByText("刚刚会话")
    const items = screen.getAllByRole("listitem").map((li) => li.textContent ?? "")
    const idx = (t: string) => items.findIndex((x) => x.includes(t))
    expect(idx("今天")).toBeGreaterThanOrEqual(0)
    expect(idx("今天")).toBeLessThan(idx("刚刚会话"))
    expect(idx("刚刚会话")).toBeLessThan(idx("昨天"))
    expect(idx("昨天")).toBeLessThan(idx("昨日会话"))
    expect(idx("昨日会话")).toBeLessThan(idx("更早"))
    expect(idx("更早")).toBeLessThan(idx("旧会话"))
    expect(screen.queryByText(/的对话/)).not.toBeInTheDocument() // 区头已删
  })

  it("重命名:菜单 → input → Enter 调 patchSession", async () => {
    const patch = vi.spyOn(api, "patchSession").mockResolvedValue(S1 as never)
    render(wrap(<SessionList />))
    await screen.findByText("标题一")
    fireEvent.click(screen.getByRole("button", { name: "标题一 更多操作" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "重命名" }))
    const input = await screen.findByDisplayValue("标题一")
    fireEvent.change(input, { target: { value: "新标题" } })
    fireEvent.keyDown(input, { key: "Enter" })
    await waitFor(() => expect(patch).toHaveBeenCalledWith("s1", { title: "新标题" }))
  })

  it("删除两次点击调 deleteSession,清掉当前选中", async () => {
    const del = vi.spyOn(api, "deleteSession").mockResolvedValue(undefined)
    render(wrap(<SessionList />))
    await screen.findByText("标题一")
    fireEvent.click(screen.getByRole("button", { name: "标题一 更多操作" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "删除" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "确认删除?" }))
    await waitFor(() => expect(del).toHaveBeenCalledWith("s1"))
    await waitFor(() => expect(useStore.getState().sessionId).toBeNull())
  })
})

describe("SessionList 定时任务标记", () => {
  it("定时产物会话显示定时标 + 未读点", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue([
      { ...S1, scheduled_task_id: "t1", unread: true },
    ] as never)
    render(wrap(<SessionList />))
    expect(await screen.findByText("标题一")).toBeInTheDocument()
    expect(screen.getByLabelText("定时任务产物")).toBeInTheDocument()
    expect(screen.getByLabelText("未读")).toBeInTheDocument()
  })

  it("打开未读会话调 markSessionRead", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue([
      { ...S1, scheduled_task_id: "t1", unread: true },
    ] as never)
    const mark = vi.spyOn(api, "markSessionRead").mockResolvedValue(undefined)
    render(wrap(<SessionList />))
    fireEvent.click(await screen.findByText("标题一"))
    await waitFor(() => expect(mark).toHaveBeenCalledWith("s1"))
  })

  it("已读普通会话不显示未读点/定时标", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue([
      { ...S1, unread: false, scheduled_task_id: null },
    ] as never)
    render(wrap(<SessionList />))
    await screen.findByText("标题一")
    expect(screen.queryByLabelText("未读")).toBeNull()
    expect(screen.queryByLabelText("定时任务产物")).toBeNull()
  })
})
