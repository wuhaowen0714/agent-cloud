import { type FormEvent, useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"

type Mode = "login" | "register"

function humanError(raw: string, mode: Mode): string {
  if (raw.includes("409")) return "该邮箱已被注册,请直接登录"
  if (raw.includes("401")) return "邮箱或密码不正确"
  if (raw.includes("422")) return "邮箱格式不正确,或密码太短(至少 8 位)"
  return mode === "login" ? "登录失败,请重试" : "注册失败,请重试"
}

export function AuthGate() {
  const setAuth = useStore((s) => s.setAuth)
  const [mode, setMode] = useState<Mode>("login")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (mode === "register" && password.length < 8) {
      setError("密码至少 8 位")
      return
    }
    setBusy(true)
    try {
      const user =
        mode === "login"
          ? await api.login(email.trim(), password)
          : await api.register(email.trim(), password)
      setAuth(user)
    } catch (err) {
      setError(humanError(String(err), mode))
    } finally {
      setBusy(false)
    }
  }

  const field =
    "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-100"

  return (
    <div className="flex h-full items-center justify-center bg-slate-50 p-6">
      <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="mb-6 flex flex-col items-center gap-2">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-600 text-lg font-bold text-white">
            A
          </span>
          <h1 className="text-lg font-semibold tracking-tight text-slate-800">Agent Cloud</h1>
          <p className="text-sm text-slate-400">
            {mode === "login" ? "登录到你的工作区" : "创建一个新账户"}
          </p>
        </div>

        <form className="space-y-3" onSubmit={submit}>
          <div className="space-y-1">
            <label className="text-xs font-medium text-slate-500">邮箱</label>
            <input
              type="email"
              required
              autoFocus
              autoComplete="email"
              className={field}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-slate-500">密码</label>
            <input
              type="password"
              required
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              className={field}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === "register" ? "至少 8 位" : "••••••••"}
            />
          </div>

          {error && (
            <div className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">{error}</div>
          )}

          <button
            type="submit"
            disabled={busy || !email || !password}
            className="w-full rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? "请稍候…" : mode === "login" ? "登录" : "注册"}
          </button>
        </form>

        <div className="mt-5 text-center text-sm text-slate-400">
          {mode === "login" ? "还没有账户?" : "已有账户?"}
          <button
            type="button"
            className="ml-1 font-medium text-brand-600 hover:text-brand-700"
            onClick={() => {
              setMode(mode === "login" ? "register" : "login")
              setError(null)
            }}
          >
            {mode === "login" ? "注册" : "登录"}
          </button>
        </div>
      </div>
    </div>
  )
}
