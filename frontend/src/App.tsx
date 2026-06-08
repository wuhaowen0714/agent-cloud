import { useEffect, useState } from "react"
import { refreshAccess } from "./api/auth"
import { api } from "./api/client"
import { AuthGate } from "./components/AuthGate"
import { ChatView } from "./components/ChatView"
import { FileDrawer } from "./components/files/FileDrawer"
import { SettingsDrawer } from "./components/settings/SettingsDrawer"
import { Sidebar } from "./components/Sidebar"
import { useStore } from "./store"

export default function App() {
  const [booting, setBooting] = useState(true)
  const user = useStore((s) => s.user)

  // 启动:用 httpOnly refresh cookie 静默换 access,再拉 me;成功则进入主界面,否则登录页。
  useEffect(() => {
    void (async () => {
      const tok = await refreshAccess()
      if (tok) {
        const u = await api.me().catch(() => null)
        useStore.getState().setAuth(u)
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
      <main className="flex min-w-0 flex-1 flex-col bg-slate-50">
        <ChatView />
      </main>
      <FileDrawer />
      <SettingsDrawer />
    </div>
  )
}
