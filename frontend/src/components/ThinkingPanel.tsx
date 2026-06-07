import { useState } from "react"

// 思考块:默认折叠;active(流式中且是当前最后一块)时自动展开,模型开始动作/回答后自动收起。
// 用户手动点击后以用户意愿为准(override 覆盖 active)。超长内容卡片内滚动。
export function ThinkingPanel({ text, active = false }: { text: string; active?: boolean }) {
  const [override, setOverride] = useState<boolean | null>(null)
  const open = override ?? active
  if (!text) return null
  return (
    <div className="mt-1 text-xs">
      <button className="text-slate-400 hover:text-slate-600" onClick={() => setOverride(!open)}>
        {open ? "▾ 思考" : "▸ 思考"}
      </button>
      {open && (
        <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 font-mono text-slate-500">
          {text}
        </pre>
      )}
    </div>
  )
}
