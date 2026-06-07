import { AgentSelector } from "./AgentSelector"
import { FileButton } from "./files/FileButton"
import { SessionList } from "./SessionList"
import { UserBar } from "./UserBar"

export function Sidebar() {
  return (
    <aside className="flex w-72 flex-col gap-3 border-r border-slate-200 bg-white p-3">
      <div className="text-sm font-semibold text-slate-800">agent-cloud</div>
      <UserBar />
      <AgentSelector />
      <div className="border-t border-slate-100" />
      <FileButton />
      <SessionList />
    </aside>
  )
}
