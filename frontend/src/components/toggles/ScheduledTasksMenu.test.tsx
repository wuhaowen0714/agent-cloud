import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../../api/client"
import { useStore } from "../../store"
import type { AgentConfig, ScheduledTask } from "../../types"
import { ScheduledTasksMenu } from "./ScheduledTasksMenu"

const agent = (over: Partial<AgentConfig> = {}): AgentConfig => ({
  id: "a1",
  user_id: "u1",
  name: "助手",
  model: "m",
  provider: "p",
  thinking_level: null,
  enabled_tools: [],
  permissions: {},
  key_ref: null,
  ...over,
})
const task = (over: Partial<ScheduledTask> = {}): ScheduledTask => ({
  id: "t1",
  user_id: "u1",
  agent_config_id: "a1",
  name: "每日新闻",
  prompt: "总结",
  schedule_kind: "cron",
  schedule_expr: "0 9 * * *",
  schedule_tz: "Asia/Shanghai",
  enabled: true,
  next_run_at: "2026-06-14T01:00:00+00:00",
  last_run_at: null,
  last_status: null,
  last_error: null,
  last_delivery_error: null,
  last_run_session_id: null,
  created_at: "2026-06-13T00:00:00+00:00",
  ...over,
})

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

beforeEach(() => {
  useStore.setState({ userId: "u1", agentId: "a1" })
  vi.spyOn(api, "listAgents").mockResolvedValue([agent()])
})
afterEach(() => vi.restoreAllMocks())

describe("ScheduledTasksMenu", () => {
  it("列出已有任务", async () => {
    vi.spyOn(api, "listScheduledTasks").mockResolvedValue([task()])
    render(wrap(<ScheduledTasksMenu />))
    expect(await screen.findByText("每日新闻")).toBeInTheDocument()
  })

  it("空态", async () => {
    vi.spyOn(api, "listScheduledTasks").mockResolvedValue([])
    render(wrap(<ScheduledTasksMenu />))
    expect(await screen.findByText(/还没有定时任务/)).toBeInTheDocument()
  })

  it("创建任务调 createScheduledTask", async () => {
    vi.spyOn(api, "listScheduledTasks").mockResolvedValue([])
    const create = vi.spyOn(api, "createScheduledTask").mockResolvedValue(task())
    render(wrap(<ScheduledTasksMenu />))
    await screen.findByText(/还没有定时任务/)
    fireEvent.change(screen.getByLabelText("任务名"), { target: { value: "晨报" } })
    fireEvent.change(screen.getByLabelText("提示词"), { target: { value: "总结昨日" } })
    fireEvent.change(screen.getByLabelText("排期表达式"), { target: { value: "0 8 * * *" } })
    fireEvent.click(screen.getByRole("button", { name: "创建" }))
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
    expect(create.mock.calls[0][0]).toMatchObject({
      name: "晨报",
      prompt: "总结昨日",
      agent_config_id: "a1",
      schedule_kind: "cron",
      schedule_expr: "0 8 * * *",
    })
  })

  it("删除任务调 deleteScheduledTask", async () => {
    vi.spyOn(api, "listScheduledTasks").mockResolvedValue([task()])
    const del = vi.spyOn(api, "deleteScheduledTask").mockResolvedValue(undefined)
    render(wrap(<ScheduledTasksMenu />))
    await screen.findByText("每日新闻")
    fireEvent.click(screen.getByRole("button", { name: "删除 每日新闻" }))
    await waitFor(() => expect(del).toHaveBeenCalledWith("t1"))
  })
})
