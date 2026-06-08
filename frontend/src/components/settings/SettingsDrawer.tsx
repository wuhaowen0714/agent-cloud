import { useState } from "react"
import { useStore } from "../../store"
import { AgentSettings } from "./AgentSettings"
import { SkillsPanel } from "./SkillsPanel"

export function SettingsDrawer() {
  const open = useStore((s) => s.settingsOpen)
  const close = useStore((s) => s.closeSettings)
  const userId = useStore((s) => s.userId)
  const [tab, setTab] = useState<"agent" | "skills">("agent")
  if (!open || !userId) return null
  const tabCls = (t: string) =>
    `px-3 py-1.5 text-sm ${
      tab === t
        ? "border-b-2 border-brand-500 font-medium text-brand-700"
        : "text-slate-500 hover:text-slate-700"
    }`
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20" onClick={close} />
      <aside className="fixed right-0 top-0 z-50 flex h-full w-[30rem] max-w-[92vw] flex-col border-l border-slate-200 bg-white shadow-xl">
        <header className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
          <span className="text-sm font-semibold text-slate-800">设置</span>
          <button className="text-slate-400 hover:text-slate-700" onClick={close}>
            ✕
          </button>
        </header>
        <div className="flex border-b border-slate-100">
          <button className={tabCls("agent")} onClick={() => setTab("agent")}>
            Agent
          </button>
          <button className={tabCls("skills")} onClick={() => setTab("skills")}>
            技能
          </button>
        </div>
        <div className="flex-1 overflow-auto p-3">
          {tab === "agent" ? <AgentSettings /> : <SkillsPanel />}
        </div>
      </aside>
    </>
  )
}
