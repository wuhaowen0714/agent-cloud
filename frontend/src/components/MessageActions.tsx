import { Check, Copy, GitBranch, Undo2 } from "lucide-react"
import { type ReactNode, useEffect, useState } from "react"
import { copyText } from "../clipboard"

// 单个图标按钮 + 自绘 tooltip。不用原生 title:它要悬停约 1s 且鼠标基本不动才弹,
// 22px 的小图标上凑不满,表现成"时有时无"。自绘 span 走 hover 300ms 即显,确定出现。
// forceTip(复制反馈)时无视 hover 直接显示。
function ActionBtn({
  label,
  tip,
  forceTip = false,
  onClick,
  children,
}: {
  label: string
  tip: string
  forceTip?: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="group/btn relative rounded p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
    >
      {children}
      <span
        className={`pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 -translate-x-1/2 whitespace-nowrap rounded-md bg-slate-800 px-1.5 py-0.5 text-[11px] text-white transition-opacity ${
          forceTip ? "opacity-100" : "opacity-0 group-hover/btn:opacity-100 group-hover/btn:delay-300"
        }`}
      >
        {tip}
      </span>
    </button>
  )
}

// 消息 hover 操作行:复制始终在;回滚/fork 仅当父级传了回调(=用户消息)才出现。
// 行的显隐由父级的 `group` hover 控制(group-hover:opacity-100)。
export function MessageActions({
  text,
  onRollback,
  onFork,
}: {
  text: string
  onRollback?: () => void
  onFork?: () => void
}) {
  // 复制结果反馈:成功/失败都要可感知(HTTP 公网下 clipboard API 不存在,copyText 内部
  // 退回 execCommand;真失败也不能再无声无息)。短暂显示后回常态。
  const [copied, setCopied] = useState<"ok" | "fail" | null>(null)
  useEffect(() => {
    if (copied === null) return
    const t = setTimeout(() => setCopied(null), 1600)
    return () => clearTimeout(t)
  }, [copied])

  return (
    <div className="flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
      {/* 文本为空(如纯工具调用的助手回合)不给复制钮 */}
      {text && (
        <ActionBtn
          label="复制"
          tip={copied === "ok" ? "已复制" : copied === "fail" ? "复制失败" : "复制"}
          forceTip={copied !== null}
          onClick={() => void copyText(text).then((ok) => setCopied(ok ? "ok" : "fail"))}
        >
          {copied === "ok" ? (
            <Check className="h-3.5 w-3.5 text-emerald-600" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
        </ActionBtn>
      )}
      {onRollback && (
        <ActionBtn label="回滚到此处" tip="回滚到此处(删除其后消息)" onClick={onRollback}>
          <Undo2 className="h-3.5 w-3.5" />
        </ActionBtn>
      )}
      {onFork && (
        <ActionBtn label="Fork 新会话" tip="Fork:从这里开新会话分支" onClick={onFork}>
          <GitBranch className="h-3.5 w-3.5" />
        </ActionBtn>
      )}
    </div>
  )
}
