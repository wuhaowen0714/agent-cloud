import { create } from "zustand"
import type { Block } from "./blocks"

// 进行中回合的实时聚合(由 SSE 事件填充)。blocks 按时间顺序记录思考/正文/工具,渲染即还原时序。
export interface LiveTurn {
  userText: string
  sessionId: string
  blocks: Block[]
  status: "streaming" | "done" | "error"
  errorMessage?: string
}

interface AppState {
  userId: string | null
  agentId: string | null
  sessionId: string | null
  live: LiveTurn | null
  fileDrawerOpen: boolean
  setUser: (id: string | null) => void
  setAgent: (id: string | null) => void
  setSession: (id: string | null) => void
  startLive: (userText: string, sessionId: string) => void
  setLive: (fn: (t: LiveTurn) => LiveTurn) => void
  clearLive: () => void
  toggleFileDrawer: () => void
}

const EMPTY: LiveTurn = { userText: "", sessionId: "", blocks: [], status: "streaming" }

export const useStore = create<AppState>((set) => ({
  userId: localStorage.getItem("ac.userId"),
  agentId: null,
  sessionId: null,
  live: null,
  fileDrawerOpen: false,
  setUser: (id) => {
    if (id) localStorage.setItem("ac.userId", id)
    else localStorage.removeItem("ac.userId")
    set({ userId: id, agentId: null, sessionId: null })
  },
  setAgent: (id) => set({ agentId: id, sessionId: null }),
  setSession: (id) => set({ sessionId: id, live: null }),
  startLive: (userText, sessionId) => set({ live: { ...EMPTY, userText, sessionId, blocks: [] } }),
  setLive: (fn) => set((s) => (s.live ? { live: fn(s.live) } : {})),
  clearLive: () => set({ live: null }),
  toggleFileDrawer: () => set((s) => ({ fileDrawerOpen: !s.fileDrawerOpen })),
}))
