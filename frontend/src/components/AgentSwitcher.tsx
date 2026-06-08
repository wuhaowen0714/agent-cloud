import { useQuery } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"

/** 当前 agent 显示 + 点开 popover:切换 agent / agent 设置 / 新建 agent。替换原生 select。 */
export function AgentSwitcher() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const setAgent = useStore((s) => s.setAgent)
  const openSettings = useStore((s) => s.openSettings)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })

  // 点击外部关闭
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  const current = agents.find((a) => a.id === agentId)
  const item =
    "flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm hover:bg-slate-100 disabled:opacity-40"

  return (
    <div ref={ref} className="relative">
      <button
        className="flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-left text-sm shadow-sm transition hover:border-slate-300 hover:bg-slate-50"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="min-w-0 flex-1 truncate">
          {current ? (
            <>
              <span className="font-medium text-slate-800">{current.name}</span>
              <span className="ml-1.5 text-xs text-slate-400">{current.model}</span>
            </>
          ) : (
            <span className="text-slate-400">选择 / 新建 agent…</span>
          )}
        </span>
        <span className="shrink-0 text-xs text-slate-400">▾</span>
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-30 mt-1.5 rounded-xl border border-slate-200 bg-white p-1.5 shadow-pop">
          <div className="max-h-60 overflow-auto">
            {agents.length === 0 && (
              <div className="px-3 py-2 text-xs text-slate-400">还没有 agent,先新建一个</div>
            )}
            {agents.map((a) => (
              <button
                key={a.id}
                className={item}
                onClick={() => {
                  setAgent(a.id)
                  setOpen(false)
                }}
              >
                <span className="w-3.5 shrink-0 text-brand-600">{a.id === agentId ? "✓" : ""}</span>
                <span className="min-w-0 flex-1 truncate text-slate-700">{a.name}</span>
                <span className="shrink-0 text-xs text-slate-400">{a.model}</span>
              </button>
            ))}
          </div>
          <div className="my-1 border-t border-slate-100" />
          <button
            className={`${item} text-slate-600`}
            disabled={!agentId}
            onClick={() => {
              openSettings()
              setOpen(false)
            }}
          >
            <span className="w-3.5 shrink-0 text-center">⚙</span>
            <span>agent 设置</span>
          </button>
          <button
            className={`${item} text-slate-600`}
            onClick={() => {
              setAgent(null)
              openSettings()
              setOpen(false)
            }}
          >
            <span className="w-3.5 shrink-0 text-center">＋</span>
            <span>新建 agent</span>
          </button>
        </div>
      )}
    </div>
  )
}
