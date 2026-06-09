import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { api } from "../../api/client"
import { Button, Textarea } from "../ui"

/**
 * 记忆块查看/编辑/清空(自整合单块记忆,spec 2026-06-09)。
 * scope=user:跨该用户所有 agent 的个人记忆;scope=agent:某 agent 专属(需 agentId)。
 * agent 自动维护,这里给用户手动纠错/遗忘的兜底入口。
 */
export function MemoryPanel({
  scope,
  agentId,
  hint,
}: {
  scope: "user" | "agent"
  agentId?: string
  hint?: string
}) {
  const qc = useQueryClient()
  const queryKey = ["memory", scope, agentId ?? null]
  const { data } = useQuery({ queryKey, queryFn: () => api.getMemory(scope, agentId) })
  const [text, setText] = useState("")
  const [saved, setSaved] = useState(false)
  // 仅首次加载灌入,之后不覆盖用户正在编辑的内容。
  const inited = useRef(false)
  useEffect(() => {
    if (data && !inited.current) {
      setText(data.content)
      inited.current = true
    }
  }, [data])

  const invalidate = () => qc.invalidateQueries({ queryKey })
  const save = useMutation({
    mutationFn: () => api.putMemory(scope, text, agentId),
    onSuccess: () => {
      invalidate()
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    },
  })
  const clear = useMutation({
    mutationFn: () => api.clearMemory(scope, agentId),
    onSuccess: () => {
      setText("")
      invalidate()
    },
  })

  return (
    <div className="space-y-2">
      <Textarea
        className="h-40 font-mono text-xs"
        placeholder={
          scope === "user"
            ? "关于你的长期记忆(agent 自动维护,可手动编辑)"
            : "这个 agent 学到的记忆(≠ 指令/人设)"
        }
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {hint && <p className="text-xs text-slate-400">{hint}</p>}
      <div className="flex items-center gap-2">
        <Button disabled={save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "保存中…" : "保存"}
        </Button>
        <Button variant="ghost" disabled={clear.isPending} onClick={() => clear.mutate()}>
          清空
        </Button>
        {saved && <span className="text-xs font-medium text-brand-600">已保存 ✓</span>}
      </div>
    </div>
  )
}
