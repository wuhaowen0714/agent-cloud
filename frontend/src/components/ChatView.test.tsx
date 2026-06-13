import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import * as stream from "../api/stream"
import { useStore } from "../store"
import type { Message } from "../types"
import { ChatView } from "./ChatView"

const userMsg = (text: string): Message => ({
  id: "u1",
  seq: 0,
  role: "user",
  content: { text, tool_calls: [], tool_results: [] },
  created_at: "2026-06-13T00:00:00Z",
})

beforeEach(() => {
  useStore.setState({ userId: "u1", agentId: null, sessionId: "s1", live: null, compactions: {} })
  vi.spyOn(api, "listAgents").mockResolvedValue([])
  vi.spyOn(stream, "resumeTurn").mockResolvedValue(null) // 挂载时无在跑回合
})
afterEach(() => {
  useStore.setState({ userId: null, agentId: null, sessionId: null, live: null, compactions: {} })
  vi.restoreAllMocks()
})

describe("ChatView 停止/出错不重复渲染用户提问", () => {
  it("出错(取消)后不刷新 messages —— 用户提问只渲染一条", async () => {
    // 首次挂载:空历史。若出错后误刷,后端已落库的该用户消息会被拉回来。
    vi.spyOn(api, "listMessages")
      .mockResolvedValueOnce([])
      .mockResolvedValue([userMsg("你好")])
    // streamTurn:立即发 error 事件(模拟「停止」触发的 SSE error),done 立即 resolve。
    vi.spyOn(stream, "streamTurn").mockImplementation((_sid, _text, onEvent) => {
      onEvent({ type: "error", message: "turn cancelled", recoverable: false })
      return { done: Promise.resolve(), abort: () => {} }
    })

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidate = vi.spyOn(qc, "invalidateQueries")
    const wrap = (ui: ReactNode) => <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
    render(wrap(<ChatView />))

    await waitFor(() => expect(api.listMessages).toHaveBeenCalled()) // 首次历史加载

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "你好" } })
    fireEvent.click(screen.getByRole("button", { name: "发送" }))

    // consume 收尾两分支都会刷 sessions;等到它,确保 consume 已完整跑完(含可能的 messages 刷新)。
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["sessions"] }))

    // 根因:出错路径绝不刷新 messages(否则把已落库的同一条用户消息拉回来与 live.userText 重复)。
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ["messages", "s1"] })
    // 用户可见结果:只有一条「你好」。
    expect(screen.getAllByText("你好")).toHaveLength(1)
  })
})
