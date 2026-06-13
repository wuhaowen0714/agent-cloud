import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "../../api/client"
import { useStore } from "../../store"
import { Button, Input, SettingGroup, SettingRow } from "../ui"

const EMPTY = { name: "", base_url: "", api_key: "", models: [] as string[] }

export function KeysPanel() {
  const userId = useStore((s) => s.userId)
  const qc = useQueryClient()
  const [form, setForm] = useState(EMPTY)
  const [modelDraft, setModelDraft] = useState("")

  const { data: creds = [] } = useQuery({
    queryKey: ["credentials", userId],
    queryFn: () => api.listCredentials(),
    enabled: !!userId,
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ["credentials", userId] })
  const create = useMutation({
    mutationFn: () => api.createCredential(form),
    onSuccess: () => {
      setForm(EMPTY)
      setModelDraft("")
      refresh()
    },
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteCredential(id),
    onSuccess: refresh,
  })

  const addModel = () => {
    const m = modelDraft.trim()
    if (m && !form.models.includes(m)) setForm({ ...form, models: [...form.models, m] })
    setModelDraft("")
  }

  return (
    <div className="space-y-5">
      <SettingGroup label="已保存的 provider">
        {creds.length === 0 ? (
          <div className="px-3.5 py-4 text-center text-xs text-slate-400">
            还没有 provider,下面添加一个
          </div>
        ) : (
          creds.map((c) => (
            <SettingRow
              key={c.id}
              label={c.name}
              hint={`${c.masked}${c.base_url ? ` · ${c.base_url}` : ""} · ${
                c.models.length ? c.models.join(", ") : "未配模型"
              }`}
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
        <SettingGroup label="添加 provider">
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
          <SettingRow label="模型" hint="该 provider 下可用的模型,可加多个" block>
            <div className="space-y-2">
              {form.models.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {form.models.map((m) => (
                    <span
                      key={m}
                      className="inline-flex items-center gap-1 rounded-lg bg-slate-100 px-2 py-1 text-xs text-slate-600"
                    >
                      {m}
                      <button
                        type="button"
                        aria-label={`删除 ${m}`}
                        className="text-slate-400 transition hover:text-red-600"
                        onClick={() =>
                          setForm({ ...form, models: form.models.filter((x) => x !== m) })
                        }
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <div className="flex gap-2">
                <Input
                  placeholder="模型名,Enter 添加"
                  value={modelDraft}
                  onChange={(e) => setModelDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault()
                      addModel()
                    }
                  }}
                />
                <Button
                  type="button"
                  variant="secondary"
                  onClick={addModel}
                  disabled={!modelDraft.trim()}
                >
                  添加
                </Button>
              </div>
            </div>
          </SettingRow>
        </SettingGroup>
        <Button type="submit" disabled={!form.name || !form.api_key || create.isPending}>
          {create.isPending ? "保存中…" : "保存"}
        </Button>
      </form>

      <p className="text-xs text-slate-400">
        Key 加密存储,只显示掩码。在输入框上方的模型选择器里按 provider 选用这些模型。
      </p>
    </div>
  )
}
