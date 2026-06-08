import { create } from "zustand"
import { setAccess, setOnUnauth } from "./api/auth"
import type { Block } from "./blocks"
import type { User } from "./types"

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
  user: User | null
  userId: string | null // 由 user 派生(user?.id),组件/query-key 仍按 userId 用
  agentId: string | null
  sessionId: string | null
  live: LiveTurn | null
  fileDrawerOpen: boolean
  settingsOpen: boolean
  setAuth: (user: User | null) => void
  logout: () => void
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

export const useStore = create<AppState>((set, get) => ({
  user: null, // 由 bootstrap(refresh→me)决定,不再从 localStorage 假造
  userId: null,
  agentId: null,
  // 持久化当前会话:刷新后自动回到原会话(并触发 resume 重挂在跑的回合)。
  sessionId: localStorage.getItem("ac.sessionId"),
  live: null,
  fileDrawerOpen: false,
  settingsOpen: false,
  setAuth: (user) => {
    const uid = user?.id ?? null
    const prev = get().userId
    // 切到「另一个」非空用户 → 清掉上一个用户的会话/agent 归属;bootstrap(null→user)或
    // 重确认同一用户则保留,以便刷新后回到原会话。
    if (prev !== null && prev !== uid) {
      localStorage.removeItem("ac.sessionId")
      set({ user, userId: uid, agentId: null, sessionId: null, live: null, settingsOpen: false })
    } else {
      set({ user, userId: uid })
    }
  },
  logout: () => {
    setAccess(null) // 丢弃内存里的 access(refresh cookie 由 /auth/logout 吊销)
    localStorage.removeItem("ac.sessionId")
    set({
      user: null,
      userId: null,
      agentId: null,
      sessionId: null,
      live: null,
      fileDrawerOpen: false,
      settingsOpen: false,
    })
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

// 401 刷新也失败时,api 层会调用 onUnauth → 这里登出回到登录页。
setOnUnauth(() => useStore.getState().logout())
