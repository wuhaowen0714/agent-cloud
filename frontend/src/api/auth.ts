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
