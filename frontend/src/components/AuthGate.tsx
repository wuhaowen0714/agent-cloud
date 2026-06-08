import { type FormEvent, useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"
import { Button, Field, Input } from "./ui"

type Mode = "login" | "register"

// 鸭子类型读 HttpError.status(不 import 类型,免得组件测试 mock 掉 ../api/client 时拿不到)。
function statusOf(err: unknown): number {
  return typeof err === "object" && err !== null && "status" in err
    ? Number((err as { status: unknown }).status)
    : 0
}

function humanError(status: number, mode: Mode): string {
  if (status === 409) return "该邮箱已被注册,请直接登录"
  if (status === 401) return "邮箱或密码不正确"
  if (status === 422) return "邮箱格式不正确,或密码太短(至少 8 位)"
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
      setError(humanError(statusOf(err), mode))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-sm rounded-2xl border border-slate-200/80 bg-white p-8 shadow-pop">
        <div className="mb-7 flex flex-col items-center gap-2.5">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-400 to-brand-600 text-xl font-bold text-white shadow-sm">
            A
          </span>
          <h1 className="text-lg font-semibold tracking-tight text-slate-800">Agent Cloud</h1>
          <p className="text-sm text-slate-400">
            {mode === "login" ? "登录到你的工作区" : "创建一个新账户"}
          </p>
        </div>

        <form className="space-y-3.5" onSubmit={submit}>
          <Field label="邮箱">
            <Input
              type="email"
              required
              autoFocus
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
            />
          </Field>
          <Field label="密码">
            <Input
              type="password"
              required
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === "register" ? "至少 8 位" : "••••••••"}
            />
          </Field>

          {error && (
            <div className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">{error}</div>
          )}

          <Button type="submit" className="w-full" disabled={busy || !email || !password}>
            {busy ? "请稍候…" : mode === "login" ? "登录" : "注册"}
          </Button>
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
