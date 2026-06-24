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
  it("今天默认展开 + 顺序;昨天/更早默认折叠,点击展开", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue([
      { ...S1, id: "old", title: "旧会话", last_active_at: day(40) },
      { ...S1, id: "yesterday", title: "昨日会话", last_active_at: day(1) },
      { ...S1, id: "now", title: "刚刚会话", last_active_at: day(0) },
    ] as never)
    render(wrap(<SessionList />))
    // 今天默认展开:刚刚会话可见,且在「今天」标题之后、「昨天」标题之前
    await screen.findByText("刚刚会话")
    const items = screen.getAllByRole("listitem").map((li) => li.textContent ?? "")
    const idx = (t: string) => items.findIndex((x) => x.includes(t))
    expect(idx("今天")).toBeGreaterThanOrEqual(0)
    expect(idx("今天")).toBeLessThan(idx("刚刚会话"))
    expect(idx("刚刚会话")).toBeLessThan(idx("昨天"))
    // 昨天/更早默认折叠:组标题在,但其会话不渲染
    expect(screen.getByText("昨天")).toBeInTheDocument()
    expect(screen.getByText("更早")).toBeInTheDocument()
    expect(screen.queryByText("昨日会话")).toBeNull()
    expect(screen.queryByText("旧会话")).toBeNull()
    // 点击「昨天」展开 → 昨日会话出现
    fireEvent.click(screen.getByText("昨天"))
    expect(await screen.findByText("昨日会话")).toBeInTheDocument()
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

  it("分组清除:两次点击调 bulkDeleteSessions 传该组 id,真正删掉当前会话则退出", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue([
      { ...S1, id: "s1", title: "今天甲", last_active_at: day(0) },
      { ...S1, id: "s2", title: "今天乙", last_active_at: day(0) },
    ] as never)
    const bulk = vi.spyOn(api, "bulkDeleteSessions").mockResolvedValue({ deleted: 2, skipped: [] })
    render(wrap(<SessionList />))
    await screen.findByText("今天甲")
    // 第一次点进入二次确认,第二次执行
    fireEvent.click(screen.getByRole("button", { name: "清除今天" }))
    fireEvent.click(await screen.findByText("清除 2 个?"))
    await waitFor(() => expect(bulk).toHaveBeenCalledTimes(1))
    expect(new Set(bulk.mock.calls[0][0])).toEqual(new Set(["s1", "s2"]))
    await waitFor(() => expect(useStore.getState().sessionId).toBeNull()) // s1(当前)被删 → 退出
  })

  it("分组清除:当前会话被 busy 跳过(在 skipped 里)则不退出,并提示", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue([
      { ...S1, id: "s1", title: "今天甲", last_active_at: day(0) },
    ] as never)
    vi.spyOn(api, "bulkDeleteSessions").mockResolvedValue({ deleted: 0, skipped: ["s1"] })
    render(wrap(<SessionList />))
    await screen.findByText("今天甲")
    fireEvent.click(screen.getByRole("button", { name: "清除今天" }))
    fireEvent.click(await screen.findByText("清除 1 个?"))
    expect(await screen.findByText("1 个进行中的会话未删")).toBeInTheDocument()
    expect(useStore.getState().sessionId).toBe("s1") // 当前会话 busy 没删 → 保持,不退出
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

  it("定时任务单独成组(置顶)且默认展开,即使其时间较早", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue([
      { ...S1, id: "now", title: "普通会话", last_active_at: day(0) },
      {
        ...S1,
        id: "sch",
        title: "喝水提醒",
        scheduled_task_id: "t1",
        unread: true,
        last_active_at: day(10),
      },
    ] as never)
    render(wrap(<SessionList />))
    expect(await screen.findByText("喝水提醒")).toBeInTheDocument() // 定时组默认展开
    const items = screen.getAllByRole("listitem").map((li) => li.textContent ?? "")
    const idx = (t: string) => items.findIndex((x) => x.includes(t))
    expect(idx("定时任务")).toBeLessThan(idx("今天")) // 定时组置顶,在普通会话(今天)之前
    expect(idx("定时任务")).toBeLessThan(idx("喝水提醒"))
  })
})
