import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "../../api/client"
import { useStore } from "../../store"

export function KeysPanel() {
  const userId = useStore((s) => s.userId)
  const qc = useQueryClient()
  const [form, setForm] = useState({ name: "", base_url: "", api_key: "" })

  const { data: creds = [] } = useQuery({
    queryKey: ["credentials", userId],
    queryFn: () => api.listCredentials(),
    enabled: !!userId,
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ["credentials", userId] })
  const create = useMutation({
    mutationFn: () => api.createCredential(form),
    onSuccess: () => {
      setForm({ name: "", base_url: "", api_key: "" })
      refresh()
    },
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteCredential(id),
    onSuccess: refresh,
  })

  const field = "w-full rounded border border-slate-300 px-2 py-1 text-sm"
  return (
    <div className="space-y-4 text-sm">
      <div className="space-y-1">
        <div className="font-medium text-slate-700">已保存的凭据</div>
        {creds.length === 0 && (
          <div className="text-xs text-slate-400">还没有凭据,下面添加一个</div>
        )}
        {creds.map((c) => (
          <div
            key={c.id}
            className="flex items-center gap-2 rounded border border-slate-200 px-2 py-1"
          >
            <span className="min-w-0 flex-1 truncate">
              <span className="text-slate-700">{c.name}</span>
              <span className="ml-2 font-mono text-xs text-slate-400">{c.masked}</span>
              {c.base_url && <span className="ml-2 text-xs text-slate-400">{c.base_url}</span>}
            </span>
            <button
              className="shrink-0 text-xs text-slate-400 hover:text-red-600"
              onClick={() => remove.mutate(c.id)}
            >
              删除
            </button>
          </div>
        ))}
      </div>
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (form.name && form.api_key) create.mutate()
        }}
      >
        <div className="font-medium text-slate-700">添加凭据</div>
        <input
          className={field}
          placeholder="名称(如 openrouter)"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <input
          className={field}
          placeholder="base_url(可选;留空 = 用平台默认端点)"
          value={form.base_url}
          onChange={(e) => setForm({ ...form, base_url: e.target.value })}
        />
        <input
          className={field}
          type="password"
          placeholder="API Key"
          value={form.api_key}
          onChange={(e) => setForm({ ...form, api_key: e.target.value })}
        />
        <button
          className="rounded bg-brand-600 px-3 py-1 text-sm text-white hover:bg-brand-700 disabled:opacity-40"
          disabled={!form.name || !form.api_key || create.isPending}
        >
          {create.isPending ? "保存中…" : "保存"}
        </button>
      </form>
      <p className="text-xs text-slate-400">
        Key 加密存储,只显示掩码;在 Agent 设置里可指定用哪个凭据。
      </p>
    </div>
  )
}
