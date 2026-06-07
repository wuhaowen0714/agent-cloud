import { create } from "zustand"
import type { ToolCall, ToolResult } from "./types"

// 进行中回合的实时聚合(由 SSE 事件填充)
export interface LiveTurn {
  thinking: string
  text: string
  toolCalls: { call: ToolCall; result?: ToolResult }[]
  status: "streaming" | "done" | "error"
  errorMessage?: string
}

interface AppState {
  userId: string | null
  agentId: string | null
  sessionId: string | null
  live: LiveTurn | null
  setUser: (id: string | null) => void
  setAgent: (id: string | null) => void
  setSession: (id: string | null) => void
  startLive: () => void
  setLive: (fn: (t: LiveTurn) => LiveTurn) => void
  clearLive: () => void
}

const EMPTY: LiveTurn = { thinking: "", text: "", toolCalls: [], status: "streaming" }

export const useStore = create<AppState>((set) => ({
  userId: localStorage.getItem("ac.userId"),
  agentId: null,
  sessionId: null,
  live: null,
  setUser: (id) => {
    if (id) localStorage.setItem("ac.userId", id)
    else localStorage.removeItem("ac.userId")
    set({ userId: id, agentId: null, sessionId: null })
  },
  setAgent: (id) => set({ agentId: id, sessionId: null }),
  setSession: (id) => set({ sessionId: id, live: null }),
  startLive: () => set({ live: { ...EMPTY, toolCalls: [] } }),
  setLive: (fn) => set((s) => (s.live ? { live: fn(s.live) } : {})),
  clearLive: () => set({ live: null }),
}))
