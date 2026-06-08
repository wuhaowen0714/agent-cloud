// access token 持有者(放内存,不持久化;刷新页面靠 httpOnly refresh cookie 静默换回)。
let _access: string | null = null
let _onUnauth: () => void = () => {}

export const setAccess = (t: string | null) => {
  _access = t
}
export const getAccess = () => _access
export const authHeader = (): Record<string, string> =>
  _access ? { Authorization: `Bearer ${_access}` } : {}

// 401 兜底回调:刷新也失败时调用(由 store 注册为 logout)。
export const setOnUnauth = (fn: () => void) => {
  _onUnauth = fn
}
export const onUnauth = () => _onUnauth()

// 单飞刷新:并发的 401 共用同一个 /auth/refresh 调用,避免刷新风暴。
let _refreshing: Promise<string | null> | null = null
export function refreshAccess(): Promise<string | null> {
  if (!_refreshing) {
    _refreshing = (async () => {
      const res = await fetch("/api/auth/refresh", { method: "POST" }) // refresh cookie 自动带
      if (!res.ok) {
        setAccess(null)
        return null
      }
      const { access_token } = (await res.json()) as { access_token: string }
      setAccess(access_token)
      return access_token
    })().finally(() => {
      _refreshing = null
    })
  }
  return _refreshing
}

// 统一的带鉴权 fetch:附 Bearer;遇 401 用 refresh cookie 静默换一枚 access 重试一次;
// 仍 401(refresh 也失效)→ 触发 onUnauth(登出)。所有需要鉴权的请求(REST/文件 blob/SSE)
// 都走这里,确保「非自愿登出」路径处处一致。retry=false 用于 login/register —— 那里的 401/409
// 是真实答案,不该被当成 access 过期去 refresh。
export async function authedFetch(input: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const withAuth = (): RequestInit => ({ ...init, headers: { ...(init.headers ?? {}), ...authHeader() } })
  let res = await fetch(input, withAuth())
  if (res.status === 401 && retry) {
    const tok = await refreshAccess()
    if (tok) res = await fetch(input, withAuth())
    if (res.status === 401) onUnauth() // 终态 401:refresh 失败或换枚后仍被拒 → 登出
  }
  return res
}
