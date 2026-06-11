import { create } from "zustand"
import { setAccess, setOnUnauth } from "./api/auth"
import { clearQueryCache } from "./api/queryClient"
import type { Block } from "./blocks"
import type { CompactResult, User } from "./types"

export type SettingsTab = "agent" | "skills" | "keys" | "memory"

// 进行中回合的实时聚合(由 SSE 事件填充)。blocks 按时间顺序记录思考/正文/工具,渲染即还原时序。
export interface LiveTurn {
  userText: string
  sessionId: string
  startedAt: string // 发送时刻(ISO);用户气泡下的时间(历史接管前的乐观显示)
  blocks: Block[]
  status: "streaming" | "done" | "error"
  errorMessage?: string
  recoverable?: boolean // 失败时是否可重试(false=如上下文过大,引导开新会话)
}

// 手动压缩状态,按 sessionId 存(与 live 单条、切会话即清不同:压缩跨会话切换须存活,
// 这样「在 A 压缩、切到 B、压缩完成」的反馈只认发起压缩的那个会话,绝不串到 B)。
export type CompactState = { phase: "running" } | { phase: "result"; result: CompactResult }

interface AppState {
  user: User | null
  userId: string | null // 由 user 派生(user?.id),组件/query-key 仍按 userId 用
  agentId: string | null
  sessionId: string | null
  live: LiveTurn | null
  compactions: Record<string, CompactState> // 按 sessionId;切会话不清(见 CompactState 注释)
  composerDraft: string | null // 待回填到输入框的文本(回滚/fork 触发);Composer 消费一次即清
  fileDrawerOpen: boolean
  settingsOpen: boolean
  settingsTab: SettingsTab
  setAuth: (user: User | null) => void
  logout: () => void
  setAgent: (id: string | null) => void
  setSession: (id: string | null) => void
  startLive: (userText: string, sessionId: string) => void
  setLive: (fn: (t: LiveTurn) => LiveTurn) => void
  clearLive: () => void
  startCompaction: (sessionId: string) => void
  finishCompaction: (sessionId: string, result: CompactResult) => void
  clearCompaction: (sessionId: string) => void
  setComposerDraft: (text: string | null) => void
  toggleFileDrawer: () => void
  openSettings: (tab?: SettingsTab) => void
  closeSettings: () => void
}

const EMPTY: LiveTurn = { userText: "", sessionId: "", startedAt: "", blocks: [], status: "streaming" }

export const useStore = create<AppState>((set, get) => ({
  user: null, // 由 bootstrap(refresh→me)决定,不再从 localStorage 假造
  userId: null,
  // 持久化当前 agent:刷新后保持选中(侧栏 agent 列表高亮 + 会话列表过滤到它)。
  agentId: localStorage.getItem("ac.agentId"),
  // 持久化当前会话:刷新后自动回到原会话(并触发 resume 重挂在跑的回合)。
  sessionId: localStorage.getItem("ac.sessionId"),
  live: null,
  compactions: {},
  composerDraft: null,
  fileDrawerOpen: false,
  settingsOpen: false,
  settingsTab: "agent",
  setAuth: (user) => {
    const uid = user?.id ?? null
    const prev = get().userId
    // 切到「另一个」非空用户 → 清掉上一个用户的会话/agent 归属;bootstrap(null→user)或
    // 重确认同一用户则保留,以便刷新后回到原会话。
    if (prev !== null && prev !== uid) {
      localStorage.removeItem("ac.sessionId")
      localStorage.removeItem("ac.agentId")
      set({ user, userId: uid, agentId: null, sessionId: null, live: null, compactions: {}, composerDraft: null, settingsOpen: false })
    } else {
      set({ user, userId: uid })
    }
  },
  logout: () => {
    setAccess(null) // 丢弃内存里的 access(refresh cookie 由 /auth/logout 吊销)
    localStorage.removeItem("ac.sessionId")
    localStorage.removeItem("ac.agentId")
    clearQueryCache() // 清掉所有缓存,避免下个用户读到上个用户残留(尤其未按 user 命名的 key)
    set({
      user: null,
      userId: null,
      agentId: null,
      sessionId: null,
      live: null,
      compactions: {},
      composerDraft: null,
      fileDrawerOpen: false,
      settingsOpen: false,
    })
  },
  setAgent: (id) => {
    if (id) localStorage.setItem("ac.agentId", id)
    else localStorage.removeItem("ac.agentId")
    localStorage.removeItem("ac.sessionId")
    set({ agentId: id, sessionId: null })
  },
  setSession: (id) => {
    if (id) localStorage.setItem("ac.sessionId", id)
    else localStorage.removeItem("ac.sessionId")
    set({ sessionId: id, live: null })
  },
  startLive: (userText, sessionId) =>
    set({ live: { ...EMPTY, userText, sessionId, blocks: [], startedAt: new Date().toISOString() } }),
  setLive: (fn) => set((s) => (s.live ? { live: fn(s.live) } : {})),
  clearLive: () => set({ live: null }),
  startCompaction: (sessionId) =>
    set((s) => ({ compactions: { ...s.compactions, [sessionId]: { phase: "running" } } })),
  finishCompaction: (sessionId, result) =>
    // 仅当该会话仍有进行中条目才写回结果:压缩进行中遇 logout/切用户会清空 compactions,
    // 此时迟到的 in-flight 结果不应复活条目(否则重新登录回到该会话会弹陈旧 flash)。
    set((s) =>
      s.compactions[sessionId]
        ? { compactions: { ...s.compactions, [sessionId]: { phase: "result", result } } }
        : {},
    ),
  setComposerDraft: (text) => set({ composerDraft: text }),
  clearCompaction: (sessionId) =>
    set((s) => {
      const { [sessionId]: _, ...rest } = s.compactions
      return { compactions: rest }
    }),
  toggleFileDrawer: () => set((s) => ({ fileDrawerOpen: !s.fileDrawerOpen })),
  openSettings: (tab = "agent") => set({ settingsOpen: true, settingsTab: tab }),
  closeSettings: () => set({ settingsOpen: false }),
}))

// 401 刷新也失败时,api 层会调用 onUnauth → 这里登出回到登录页。
setOnUnauth(() => useStore.getState().logout())
