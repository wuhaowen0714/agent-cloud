import { ChatView } from "./components/ChatView"
import { FileDrawer } from "./components/files/FileDrawer"
import { SettingsDrawer } from "./components/settings/SettingsDrawer"
import { Sidebar } from "./components/Sidebar"

export default function App() {
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
