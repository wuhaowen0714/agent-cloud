import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api, HttpError } from "../../api/client"
import { useStore } from "../../store"
import type { ScheduledTask } from "../../types"
import { Button, Input, Segmented, Switch, Textarea } from "../ui"

const KINDS: { value: string; label: string }[] = [
  { value: "cron", label: "Cron" },
  { value: "interval", label: "间隔" },
  { value: "once", label: "一次" },
]
const PLACEHOLDER: Record<string, string> = {
  cron: "0 9 * * *(每天 9 点)",
  interval: "3600 或 30m / 2h / 1d",
  once: "2026-06-14T09:00:00+08:00",
}

const statusDot = (t: ScheduledTask) =>
  t.last_status === "error"
    ? "⚠️"
    : t.last_status === "skipped"
      ? "⏭"
      : t.last_status === "ok"
        ? "✅"
        : "·"

// TopBar「定时任务」弹层:列出本人任务 + 内联创建。任务归属 user,创建用当前 agent(无则首个)。
export function ScheduledTasksMenu() {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const qc = useQueryClient()
  const { data: tasks = [] } = useQuery({
    queryKey: ["scheduledTasks", userId],
    queryFn: () => api.listScheduledTasks(),
    enabled: !!userId,
  })
  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
  })
  const invalidate = () => qc.invalidateQueries({ queryKey: ["scheduledTasks", userId] })

  const [name, setName] = useState("")
  const [prompt, setPrompt] = useState("")
  const [kind, setKind] = useState("cron")
  const [expr, setExpr] = useState("")
  const [createErr, setCreateErr] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () =>
      api.createScheduledTask({
        name,
        prompt,
        agent_config_id: agentId || agents[0]?.id || "",
        schedule_kind: kind,
        schedule_expr: expr,
      }),
    onSuccess: () => {
      setName("")
      setPrompt("")
      setExpr("")
      setCreateErr(null)
      invalidate()
    },
    onError: (e) =>
      setCreateErr(
        e instanceof HttpError && e.status === 422 ? "排期表达式无效,请检查" : "创建失败",
      ),
  })
  const patch = useMutation({
    mutationFn: (v: { id: string; enabled: boolean }) =>
      api.patchScheduledTask(v.id, { enabled: v.enabled }),
    onSettled: invalidate,
  })
  const runNow = useMutation({
    mutationFn: (id: string) => api.runScheduledTask(id),
    onSettled: invalidate,
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteScheduledTask(id),
    onSettled: invalidate,
  })

  const canCreate = Boolean(name.trim() && prompt.trim() && expr.trim() && (agentId || agents[0]))

  return (
    <div className="max-h-[70vh] overflow-auto px-1">
      <div className="space-y-1 pb-2">
        {tasks.length === 0 ? (
          <div className="px-2 py-3 text-center text-xs text-slate-400">还没有定时任务</div>
        ) : (
          tasks.map((t) => (
            <div key={t.id} className="rounded-lg px-2.5 py-1.5 hover:bg-slate-50">
              <div className="flex items-center gap-2">
                <span className="flex min-w-0 flex-1 items-center gap-1 text-xs font-medium text-slate-700">
                  <span className="shrink-0">{statusDot(t)}</span>
                  <span className="truncate">{t.name}</span>
                </span>
                <Switch
                  checked={t.enabled}
                  onChange={() => patch.mutate({ id: t.id, enabled: !t.enabled })}
                  label={`启用 ${t.name}`}
                />
              </div>
              <div className="mt-0.5 flex items-center gap-2 text-[11px] text-slate-400">
                <span className="min-w-0 flex-1 truncate">
                  {t.schedule_kind} · {t.schedule_expr}
                </span>
                <button
                  type="button"
                  className="shrink-0 hover:text-brand-600"
                  onClick={() => runNow.mutate(t.id)}
                >
                  立即运行
                </button>
                <button
                  type="button"
                  className="shrink-0 hover:text-red-600"
                  aria-label={`删除 ${t.name}`}
                  onClick={() => remove.mutate(t.id)}
                >
                  删除
                </button>
              </div>
            </div>
          ))
        )}
      </div>
      <div className="space-y-1.5 border-t border-slate-100 pt-2">
        <Input
          aria-label="任务名"
          placeholder="任务名"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Textarea
          aria-label="提示词"
          placeholder="每次运行执行的提示(自包含)"
          value={prompt}
          rows={2}
          onChange={(e) => setPrompt(e.target.value)}
        />
        <Segmented options={KINDS} value={kind} onChange={setKind} />
        <Input
          aria-label="排期表达式"
          placeholder={PLACEHOLDER[kind]}
          value={expr}
          onChange={(e) => setExpr(e.target.value)}
        />
        {createErr && <div className="px-1 text-[11px] text-red-600">{createErr}</div>}
        <Button disabled={!canCreate} onClick={() => create.mutate()}>
          创建
        </Button>
      </div>
    </div>
  )
}
