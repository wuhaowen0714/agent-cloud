import { Blocks, Bot, Brain, KeyRound } from "lucide-react"
import type { ComponentType } from "react"
import type { SettingsTab } from "../../store"

const TABS: {
  id: SettingsTab
  label: string
  Icon: ComponentType<{ size?: number; className?: string }>
}[] = [
  { id: "agent", label: "Agent", Icon: Bot },
  { id: "skills", label: "技能", Icon: Blocks },
  { id: "memory", label: "记忆", Icon: Brain },
  { id: "keys", label: "Provider Keys", Icon: KeyRound },
]

export function SettingsNav({
  tab,
  onSelect,
}: {
  tab: SettingsTab
  onSelect: (t: SettingsTab) => void
}) {
  return (
    <nav className="flex w-36 shrink-0 flex-col gap-0.5 border-r border-slate-100 p-2">
      {TABS.map(({ id, label, Icon }) => {
        const active = id === tab
        return (
          <button
            key={id}
            type="button"
            aria-current={active}
            onClick={() => onSelect(id)}
            className={`flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition ${
              active ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            <Icon size={16} className={active ? "text-brand-600" : "text-slate-400"} />
            <span className="truncate">{label}</span>
          </button>
        )
      })}
    </nav>
  )
}
