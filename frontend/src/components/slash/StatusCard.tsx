import { COMMANDS, type StatusInfo } from "./commands"

// composer 上方的「通知槽」:三种内容共用一个浮层位置。
export function StatusCard({
  kind,
  status,
  flash,
  onClose,
}: {
  kind: "status" | "help" | "flash"
  status?: StatusInfo
  flash?: string
  onClose: () => void
}) {
  return (
    <div className="absolute bottom-full left-0 right-0 z-30 mb-2 rounded-xl border border-slate-200 bg-white p-3 shadow-pop">
      <button
        type="button"
        aria-label="关闭"
        onMouseDown={(e) => {
          e.preventDefault()
          onClose()
        }}
        className="absolute right-2 top-2 flex h-6 w-6 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700"
      >
        ✕
      </button>
      {kind === "flash" && <div className="pr-6 text-sm text-slate-700">{flash}</div>}
      {kind === "status" && status && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 pr-6 text-sm">
          <dt className="text-slate-400">Agent</dt>
          <dd className="text-slate-700">{status.agentName ?? "—"}</dd>
          <dt className="text-slate-400">模型</dt>
          <dd className="text-slate-700">{status.model ?? "—"}</dd>
          <dt className="text-slate-400">Provider</dt>
          <dd className="text-slate-700">{status.provider ?? "—"}</dd>
          <dt className="text-slate-400">会话</dt>
          <dd className="text-slate-700">
            {status.sessionTitle ?? "未命名"}{" "}
            <span className="text-slate-400">({status.sessionIdShort ?? "—"})</span>
          </dd>
          <dt className="text-slate-400">消息数</dt>
          <dd className="text-slate-700">{status.messageCount}</dd>
          <dt className="text-slate-400">上下文</dt>
          <dd className="text-slate-700">
            {status.contextTokens != null ? `${status.contextTokens.toLocaleString()} tokens` : "—"}
          </dd>
        </dl>
      )}
      {kind === "help" && (
        <div className="pr-6">
          <div className="mb-1.5 text-xs font-medium text-slate-500">斜杠命令</div>
          <ul className="space-y-0.5 text-sm">
            {COMMANDS.map((c) => (
              <li key={c.name} className="flex items-center gap-3">
                <span className="font-mono text-slate-700">/{c.name}</span>
                <span className="text-xs text-slate-400">{c.hint}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
