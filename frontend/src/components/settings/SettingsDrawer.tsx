import { useStore } from "../../store"
import { AgentSettings } from "./AgentSettings"
import { KeysPanel } from "./KeysPanel"
import { SkillsPanel } from "./SkillsPanel"

type Tab = "agent" | "skills" | "keys"
const TABS: { id: Tab; label: string }[] = [
  { id: "agent", label: "Agent" },
  { id: "skills", label: "技能" },
  { id: "keys", label: "Provider Keys" },
]

export function SettingsDrawer() {
  const open = useStore((s) => s.settingsOpen)
  const close = useStore((s) => s.closeSettings)
  const userId = useStore((s) => s.userId)
  const tab = useStore((s) => s.settingsTab)
  const setTab = (t: Tab) => useStore.setState({ settingsTab: t })
  if (!open || !userId) return null
  return (
    <>
      <div className="fixed inset-0 z-40 bg-slate-900/30 backdrop-blur-sm" onClick={close} />
      <aside className="fixed right-0 top-0 z-50 flex h-full w-[30rem] max-w-[92vw] flex-col rounded-l-2xl border-l border-slate-200 bg-white shadow-pop">
        <header className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <span className="text-base font-semibold tracking-tight text-slate-800">设置</span>
          <button
            className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
            onClick={close}
          >
            ✕
          </button>
        </header>
        <div className="flex gap-5 border-b border-slate-100 px-4">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`-mb-px border-b-2 py-2.5 text-sm font-medium transition ${
                tab === t.id
                  ? "border-brand-500 text-brand-700"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-auto p-4">
          {tab === "agent" && <AgentSettings />}
          {tab === "skills" && <SkillsPanel />}
          {tab === "keys" && <KeysPanel />}
        </div>
      </aside>
    </>
  )
}
