import { useEffect, useState } from "react"
import { refreshAccess } from "./api/auth"
import { api } from "./api/client"
import { AuthGate } from "./components/AuthGate"
import { ChatView } from "./components/ChatView"
import { FileDrawer } from "./components/files/FileDrawer"
import { SettingsDrawer } from "./components/settings/SettingsDrawer"
import { Sidebar } from "./components/Sidebar"
import { useStore } from "./store"

// 模块级一次性闸:StrictMode(dev)会双跑 effect;只 bootstrap 一次,避免重复 refresh/me。
let booted = false

export default function App() {
  const [booting, setBooting] = useState(true)
  const user = useStore((s) => s.user)

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
    <div className="flex h-full">
      <Sidebar />
      <main className="flex min-w-0 flex-1 flex-col bg-gradient-to-b from-slate-50 to-slate-100/40">
        <ChatView />
      </main>
      <FileDrawer />
      <SettingsDrawer />
    </div>
  )
}
