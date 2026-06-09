import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "../../api/client"
import { useStore } from "../../store"
import { Button, Input, SettingGroup, SettingRow } from "../ui"

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
    <div className="space-y-5">
      <SettingGroup label="已保存的凭据">
        {creds.length === 0 ? (
          <div className="px-3.5 py-4 text-center text-xs text-slate-400">还没有凭据,下面添加一个</div>
        ) : (
          creds.map((c) => (
            <SettingRow
              key={c.id}
              label={c.name}
              hint={`${c.masked}${c.base_url ? ` · ${c.base_url}` : ""}`}
            >
              <button
                className="shrink-0 text-xs text-slate-400 transition hover:text-red-600"
                onClick={() => remove.mutate(c.id)}
              >
                删除
              </button>
            </SettingRow>
          ))
        )}
      </SettingGroup>

      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (form.name && form.api_key) create.mutate()
        }}
      >
        <SettingGroup label="添加凭据">
          <SettingRow label="名称" block>
            <Input
              placeholder="如 openrouter"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </SettingRow>
          <SettingRow label="Base URL" hint="可选 · 留空则用平台默认端点" block>
            <Input
              placeholder="https://…/v1"
              value={form.base_url}
              onChange={(e) => setForm({ ...form, base_url: e.target.value })}
            />
          </SettingRow>
          <SettingRow label="API Key" block>
            <Input
              type="password"
              placeholder="sk-…"
              value={form.api_key}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })}
            />
          </SettingRow>
        </SettingGroup>
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
