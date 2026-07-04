// 任务清单卡(计划模式):渲染 todo 工具的 items。在 TurnBlocks 里按「首现位置 + 本组
// blocks 内最新一次调用的内容」原位刷新(agent 每次全量重写清单,不逐卡罗列演进过程)。
export interface TodoItem {
  content: string
  status: "pending" | "in_progress" | "completed"
}

// tool_call arguments → items(不可信模型输出,逐项容错;非法项丢弃)。
export function parseTodoItems(args: Record<string, unknown>): TodoItem[] {
  const raw = args?.items
  if (!Array.isArray(raw)) return []
  const out: TodoItem[] = []
  for (const it of raw) {
    if (typeof it !== "object" || it === null) continue
    const { content, status } = it as { content?: unknown; status?: unknown }
    if (typeof content !== "string" || !content.trim()) continue
    if (status !== "pending" && status !== "in_progress" && status !== "completed") continue
    out.push({ content: content.trim(), status })
  }
  return out
}

export function TodoCard({ items }: { items: TodoItem[] }) {
  if (!items.length) return null
  const done = items.filter((i) => i.status === "completed").length
  return (
    <div className="my-2 rounded-lg border border-brand-200 bg-brand-50/50 px-3.5 py-2.5">
      <div className="mb-1.5 flex items-center gap-2 text-xs font-medium text-brand-700">
        <span>任务清单</span>
        <span className="text-brand-500">
          {done}/{items.length}
        </span>
      </div>
      <ul className="space-y-1">
        {items.map((it, i) => (
          <li key={`${i}-${it.content.slice(0, 16)}`} className="flex items-start gap-2 text-sm leading-5">
            {it.status === "completed" ? (
              <span className="mt-0.5 text-brand-600">✓</span>
            ) : it.status === "in_progress" ? (
              <span className="mt-0.5 animate-pulse text-brand-600">◐</span>
            ) : (
              <span className="mt-0.5 text-slate-300">○</span>
            )}
            <span
              className={
                it.status === "completed"
                  ? "text-slate-400 line-through"
                  : it.status === "in_progress"
                    ? "font-medium text-slate-800"
                    : "text-slate-500"
              }
            >
              {it.content}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
