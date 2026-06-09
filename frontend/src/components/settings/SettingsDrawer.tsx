import { X } from "lucide-react"
import { type SettingsTab, useStore } from "../../store"
import { AgentSettings } from "./AgentSettings"
import { KeysPanel } from "./KeysPanel"
import { MemoryPanel } from "./MemoryPanel"
import { SettingsNav } from "./SettingsNav"
import { SkillsPanel } from "./SkillsPanel"

export function SettingsDrawer() {
  const open = useStore((s) => s.settingsOpen)
  const close = useStore((s) => s.closeSettings)
  const userId = useStore((s) => s.userId)
  const tab = useStore((s) => s.settingsTab)
  const setTab = (t: SettingsTab) => useStore.setState({ settingsTab: t })
  if (!open || !userId) return null
  return (
    <>
      <div className="fixed inset-0 z-40 bg-slate-900/30 backdrop-blur-sm" onClick={close} />
      <aside className="fixed right-0 top-0 z-50 flex h-full w-[32rem] max-w-[94vw] flex-col rounded-l-2xl border-l border-slate-200 bg-white shadow-pop">
        <header className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <span className="text-base font-semibold tracking-tight text-slate-800">设置</span>
          <button
            aria-label="关闭设置"
            className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
            onClick={close}
          >
            <X size={16} />
          </button>
        </header>
        <div className="flex min-h-0 flex-1">
          <SettingsNav tab={tab} onSelect={setTab} />
          <div className="min-w-0 flex-1 overflow-auto p-4">
            {tab === "agent" && <AgentSettings />}
            {tab === "skills" && <SkillsPanel />}
            {tab === "memory" && (
              <MemoryPanel
                scope="user"
                hint="跨你所有 agent 的个人长期记忆;agent 在对话空闲/压缩时自动维护。"
              />
            )}
            {tab === "keys" && <KeysPanel />}
          </div>
        </div>
      </aside>
    </>
  )
}
