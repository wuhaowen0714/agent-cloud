import { QueryClient } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { Session } from "../types"
import { pollSessionTitle } from "./queryClient"

const sess = (title: string | null): Session => ({
  id: "s1", user_id: "u1", agent_config_id: "a1", title,
  work_subdir: "workspace", last_context_tokens: null,
})

// 只在精确 key ["sessions","u1"] 下返回数据;读错 key → undefined。这样若实现把读取
// key 写错(如漏 userId),「拿到即停」会读不到 title → 退化为烧满 maxAttempts,测试即红。
const dataAtSessionsKey = (get: () => Session[]) => (key: unknown) =>
  JSON.stringify(key) === JSON.stringify(["sessions", "u1"]) ? get() : undefined

describe("pollSessionTitle", () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it("轮询刷新 sessions,直到该会话拿到 title 就停", async () => {
    const qc = new QueryClient()
    let title: string | null = null
    vi.spyOn(qc, "getQueryData").mockImplementation(
      dataAtSessionsKey(() => [sess(title)]) as never,
    )
    const inv = vi.spyOn(qc, "invalidateQueries").mockResolvedValue(undefined as never)

    pollSessionTitle(qc, "u1", "s1", { intervalMs: 2000, maxAttempts: 5 })
    expect(inv).not.toHaveBeenCalled() // 首刷也要等一个间隔
    await vi.advanceTimersByTimeAsync(2000) // 第 1 刷:title 仍 null → 继续
    expect(inv).toHaveBeenCalledTimes(1)
    expect(inv).toHaveBeenCalledWith({ queryKey: ["sessions", "u1"] })

    title = "快排实现" // 服务端标题这时生成好了
    await vi.advanceTimersByTimeAsync(2000) // 第 2 刷:拿到 title → 停
    expect(inv).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(20000) // 之后不再刷
    expect(inv).toHaveBeenCalledTimes(2)
  })

  it("title 始终 null:到 maxAttempts 兜底停(不无限轮询)", async () => {
    const qc = new QueryClient()
    vi.spyOn(qc, "getQueryData").mockImplementation(
      dataAtSessionsKey(() => [sess(null)]) as never,
    )
    const inv = vi.spyOn(qc, "invalidateQueries").mockResolvedValue(undefined as never)

    pollSessionTitle(qc, "u1", "s1", { intervalMs: 1000, maxAttempts: 3 })
    await vi.advanceTimersByTimeAsync(60000)
    expect(inv).toHaveBeenCalledTimes(3) // 3 次后停,不再刷
  })
})
