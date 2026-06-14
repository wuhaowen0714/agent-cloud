import { useEffect, useState } from "react"
import { refreshAccess } from "./api/auth"
import { api } from "./api/client"
import { AuthGate } from "./components/AuthGate"
import { ChatView } from "./components/ChatView"
import { FileDrawer } from "./components/files/FileDrawer"
import { NotificationListener } from "./components/NotificationListener"
import { SettingsDrawer } from "./components/settings/SettingsDrawer"
import { Sidebar } from "./components/Sidebar"
import { TerminalWindow } from "./components/terminal/TerminalWindow"
import { TopBar } from "./components/TopBar"
import { useStore } from "./store"

// 模块级一次性闸:StrictMode(dev)会双跑 effect;只 bootstrap 一次,避免重复 refresh/me。
let booted = false

export default function App() {
  const [booting, setBooting] = useState(true)
  const user = useStore((s) => s.user)
  const terminalOpen = useStore((s) => s.terminalOpen)
  // 终端常驻挂载闸:首次打开后保持挂载(收起只是滑出动画,WS/PTY/缓冲保留——
  // Ghostty quick-terminal 语义)。logout 时整棵树卸载,连接随之断开,不跨用户泄漏。
  const [terminalMounted, setTerminalMounted] = useState(false)
  useEffect(() => {
    if (terminalOpen) setTerminalMounted(true)
  }, [terminalOpen])

  // 启动:用 httpOnly refresh cookie 静默换 access,再拉 me;成功则进入主界面,否则登录页。
  useEffect(() => {
    if (booted) return
    booted = true
    void (async () => {
      const tok = await refreshAccess()
      if (tok) {
        const u = await api.me().catch(() => null)
        // refresh 成功但 me 失败:别让 access 残留在内存(否则下次请求会带着上个会话的 token)。
        if (u) useStore.getState().setAuth(u)
        else useStore.getState().logout()
      }
      setBooting(false)
    })()
  }, [])

  if (booting) {
    return (
      <div className="flex h-full items-center justify-center bg-slate-50">
        <span className="animate-pulse text-sm text-slate-400">加载中…</span>
      </div>
    )
  }
  if (!user) return <AuthGate />

  return (
    // overflow-hidden:应用是「固定视口外壳,只有指定面板滚动」;兜底保证任何内部溢出
    // 都不会把 document 撑出滚动条(滚动应发生在 MessageList / 列表等 overflow-auto 里)。
    <div className="flex h-full overflow-hidden">
      <Sidebar />
      <main className="flex min-w-0 flex-1 flex-col bg-gradient-to-b from-slate-50 to-slate-100/40">
        <TopBar />
        <ChatView />
      </main>
      <FileDrawer />
      <SettingsDrawer />
      <NotificationListener />
      {terminalMounted && <TerminalWindow />}
    </div>
  )
}
