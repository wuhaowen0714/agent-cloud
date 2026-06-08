import { create } from "zustand"
import type { Block } from "./blocks"

// 进行中回合的实时聚合(由 SSE 事件填充)。blocks 按时间顺序记录思考/正文/工具,渲染即还原时序。
export interface LiveTurn {
  userText: string
  sessionId: string
  blocks: Block[]
  status: "streaming" | "done" | "error"
  errorMessage?: string
  recoverable?: boolean // 失败时是否可重试(false=如上下文过大,引导开新会话)
}

interface AppState {
  userId: string | null
  agentId: string | null
  sessionId: string | null
  live: LiveTurn | null
  fileDrawerOpen: boolean
  settingsOpen: boolean
  setUser: (id: string | null) => void
  setAgent: (id: string | null) => void
  setSession: (id: string | null) => void
  startLive: (userText: string, sessionId: string) => void
  setLive: (fn: (t: LiveTurn) => LiveTurn) => void
  clearLive: () => void
  toggleFileDrawer: () => void
  openSettings: () => void
  closeSettings: () => void
}

const EMPTY: LiveTurn = { userText: "", sessionId: "", blocks: [], status: "streaming" }

export const useStore = create<AppState>((set) => ({
  userId: localStorage.getItem("ac.userId"),
  agentId: null,
  // 持久化当前会话:刷新后自动回到原会话(并触发 resume 重挂在跑的回合)。
  sessionId: localStorage.getItem("ac.sessionId"),
  live: null,
  fileDrawerOpen: false,
  settingsOpen: false,
  setUser: (id) => {
    if (id) localStorage.setItem("ac.userId", id)
    else localStorage.removeItem("ac.userId")
    localStorage.removeItem("ac.sessionId") // 换用户清掉会话归属
    set({ userId: id, agentId: null, sessionId: null, settingsOpen: false })
  },
  setAgent: (id) => {
    localStorage.removeItem("ac.sessionId")
    set({ agentId: id, sessionId: null })
  },
  setSession: (id) => {
    if (id) localStorage.setItem("ac.sessionId", id)
    else localStorage.removeItem("ac.sessionId")
    set({ sessionId: id, live: null })
  },
  startLive: (userText, sessionId) => set({ live: { ...EMPTY, userText, sessionId, blocks: [] } }),
  setLive: (fn) => set((s) => (s.live ? { live: fn(s.live) } : {})),
  clearLive: () => set({ live: null }),
  toggleFileDrawer: () => set((s) => ({ fileDrawerOpen: !s.fileDrawerOpen })),
  openSettings: () => set({ settingsOpen: true }),
  closeSettings: () => set({ settingsOpen: false }),
}))
