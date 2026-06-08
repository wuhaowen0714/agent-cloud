import { AgentSelector } from "./AgentSelector"
import { FileButton } from "./files/FileButton"
import { SessionList } from "./SessionList"
import { UserBar } from "./UserBar"

function Label({ children }: { children: string }) {
  return <div className="text-xs font-medium uppercase tracking-wide text-slate-400">{children}</div>
}

export function Sidebar() {
  return (
    <aside className="flex w-72 flex-col gap-3 border-r border-slate-200 bg-white p-3">
      <div className="text-sm font-semibold text-slate-800">agent-cloud</div>
      <UserBar />
      <div className="space-y-1.5">
        <Label>Agent</Label>
        <AgentSelector />
      </div>
      <div className="space-y-1.5">
        <Label>工作区</Label>
        <FileButton />
      </div>
      <div className="border-t border-slate-100" />
      <SessionList />
    </aside>
  )
}
