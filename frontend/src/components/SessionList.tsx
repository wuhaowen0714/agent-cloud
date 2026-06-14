import { useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarClock } from "lucide-react"
import { Fragment, useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"
import { timeGroupLabel } from "../time"
import { RowMenu } from "./RowMenu"

export function SessionList() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const sessionId = useStore((s) => s.sessionId)
  const setSession = useStore((s) => s.setSession)
  const qc = useQueryClient()
  const [renamingId, setRenamingId] = useState<string | null>(null)

  const { data: sessions = [] } = useQuery({
    queryKey: ["sessions", userId],
    queryFn: () => api.listSessions(),
    enabled: !!userId,
  })

  // 只显示当前 agent 的会话(会话本身带 agent_config_id);未选 agent 则为空。
  // 按最近活跃降序 + 时间分组(归属由 rail/面板头部表达,区头已删)。
  const mine = agentId ? sessions.filter((s) => s.agent_config_id === agentId) : []
  const sorted = [...mine].sort(
    (a, b) => +new Date(b.last_active_at) - +new Date(a.last_active_at),
  )
  const groups: { label: string; items: typeof sorted }[] = []
  for (const s of sorted) {
    const glabel = timeGroupLabel(s.last_active_at)
    const last = groups[groups.length - 1]
    if (last?.label === glabel) last.items.push(s)
    else groups.push({ label: glabel, items: [s] })
  }
  const label = (s: (typeof mine)[number]) => s.title ?? `会话 ${s.id.slice(0, 6)}`
  const invalidate = () => qc.invalidateQueries({ queryKey: ["sessions", userId] })

  const commitRename = async (id: string, value: string, original: string) => {
    const title = value.trim()
    setRenamingId(null)
    if (!title || title === original) return
    try {
      await api.patchSession(id, { title })
      await invalidate()
    } catch {
      // 改名失败:保持原标题,不打断;maxLength 已挡住超长
    }
  }

  const removeSession = async (id: string) => {
    await api.deleteSession(id) // 409(回合进行中)→ 抛 HttpError,由 RowMenu 原位提示
    await invalidate()
    if (useStore.getState().sessionId === id) setSession(null)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ul className="min-h-0 flex-1 space-y-0.5 overflow-auto">
        {groups.map((g) => (
          <Fragment key={g.label}>
            <li className="px-1 pb-1 pt-3 text-[11px] font-medium tracking-wide text-slate-400 first:pt-0.5">
              {g.label}
            </li>
            {g.items.map((s) => (
          <li
            key={s.id}
            className={`group flex items-center gap-1 rounded-lg pr-1 transition ${
              s.id === sessionId ? "bg-brand-50" : "hover:bg-slate-100"
            }`}
          >
            {renamingId === s.id ? (
              <input
                autoFocus
                defaultValue={label(s)}
                maxLength={200}
                aria-label={`重命名 ${label(s)}`}
                onFocus={(e) => e.target.select()}
                onKeyDown={(e) => {
                  // isComposing:IME 选字的回车不算确认
                  if (e.key === "Enter" && !e.nativeEvent.isComposing)
                    void commitRename(s.id, e.currentTarget.value, label(s))
                  else if (e.key === "Escape") setRenamingId(null)
                }}
                onBlur={() => setRenamingId(null)}
                className="mx-1 my-0.5 w-full rounded-lg border border-brand-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
              />
            ) : (
              <>
                <button
                  className={`flex min-w-0 flex-1 items-center gap-1.5 px-2.5 py-2 text-left text-sm ${
                    s.id === sessionId ? "font-medium text-brand-800" : "text-slate-600"
                  }`}
                  onClick={() => {
                    setSession(s.id)
                    // 打开定时任务产出的未读会话即清角标(GET 取消息无副作用,单独端点)。
                    if (s.unread) void api.markSessionRead(s.id).then(invalidate)
                  }}
                >
                  {s.scheduled_task_id && (
                    <CalendarClock
                      size={13}
                      aria-label="定时任务产物"
                      className="shrink-0 text-slate-400"
                    />
                  )}
                  <span className="min-w-0 flex-1 truncate">{label(s)}</span>
                  {s.unread && (
                    <span
                      aria-label="未读"
                      className="h-2 w-2 shrink-0 rounded-full bg-brand-500"
                    />
                  )}
                </button>
                <RowMenu
                  ariaLabel={`${label(s)} 更多操作`}
                  visible={s.id === sessionId}
                  items={[
                    { label: "重命名", onSelect: () => setRenamingId(s.id) },
                    {
                      label: "删除",
                      danger: true,
                      confirmLabel: "确认删除?",
                      onSelect: () => removeSession(s.id),
                    },
                  ]}
                />
              </>
            )}
          </li>
            ))}
          </Fragment>
        ))}
        {agentId && mine.length === 0 && (
          <li className="px-2 py-6 text-center text-xs text-slate-400">还没有对话</li>
        )}
        {!agentId && (
          <li className="px-2 py-6 text-center text-xs text-slate-400">先选一个 agent</li>
        )}
      </ul>
    </div>
  )
}
