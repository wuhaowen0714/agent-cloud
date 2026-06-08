import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "../../api/client"
import { useStore } from "../../store"
import { Button, Field, Input } from "../ui"

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

  return (
    <div className="space-y-5 text-sm">
      <div className="space-y-2">
        <div className="text-sm font-semibold text-slate-800">已保存的凭据</div>
        {creds.length === 0 && (
          <div className="text-xs text-slate-400">还没有凭据,下面添加一个</div>
        )}
        {creds.map((c) => (
          <div
            key={c.id}
            className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2.5 shadow-card"
          >
            <span className="min-w-0 flex-1 truncate">
              <span className="font-medium text-slate-700">{c.name}</span>
              <span className="ml-2 font-mono text-xs text-slate-400">{c.masked}</span>
              {c.base_url && <span className="ml-2 text-xs text-slate-400">{c.base_url}</span>}
            </span>
            <button
              className="shrink-0 text-xs text-slate-400 transition hover:text-red-600"
              onClick={() => remove.mutate(c.id)}
            >
              删除
            </button>
          </div>
        ))}
      </div>
      <form
        className="space-y-2.5"
        onSubmit={(e) => {
          e.preventDefault()
          if (form.name && form.api_key) create.mutate()
        }}
      >
        <div className="text-sm font-semibold text-slate-800">添加凭据</div>
        <Field label="名称">
          <Input
            placeholder="如 openrouter"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </Field>
        <Field label="Base URL" hint="可选 · 留空则用平台默认端点">
          <Input
            placeholder="https://…/v1"
            value={form.base_url}
            onChange={(e) => setForm({ ...form, base_url: e.target.value })}
          />
        </Field>
        <Field label="API Key">
          <Input
            type="password"
            placeholder="sk-…"
            value={form.api_key}
            onChange={(e) => setForm({ ...form, api_key: e.target.value })}
          />
        </Field>
        <Button type="submit" disabled={!form.name || !form.api_key || create.isPending}>
          {create.isPending ? "保存中…" : "保存"}
        </Button>
      </form>
      <p className="text-xs text-slate-400">
        Key 加密存储,只显示掩码;在 Agent 设置里可指定用哪个凭据。
      </p>
    </div>
  )
}
