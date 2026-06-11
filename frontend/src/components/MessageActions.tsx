import { Copy, GitBranch, Undo2 } from "lucide-react"

// 消息 hover 操作行:复制始终在;回滚/fork 仅当父级传了回调(=用户消息)才出现。
// 透明度由父级的 `group` hover 控制(group-hover:opacity-100)。
export function MessageActions({
  text,
  onRollback,
  onFork,
}: {
  text: string
  onRollback?: () => void
  onFork?: () => void
}) {
  const btn =
    "rounded p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
  return (
    <div className="flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
      {/* 文本为空(如纯工具调用的助手回合)不给复制钮;clipboard 不可用/被拒静默吞掉 */}
      {text && (
        <button
          type="button"
          aria-label="复制"
          className={btn}
          onClick={() => void navigator.clipboard?.writeText(text)?.catch(() => {})}
        >
          <Copy className="h-3.5 w-3.5" />
        </button>
      )}
      {onRollback && (
        <button type="button" aria-label="回滚到此处" className={btn} onClick={onRollback}>
          <Undo2 className="h-3.5 w-3.5" />
        </button>
      )}
      {onFork && (
        <button type="button" aria-label="Fork 新会话" className={btn} onClick={onFork}>
          <GitBranch className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  )
}
