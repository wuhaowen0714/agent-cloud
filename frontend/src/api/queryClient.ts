import type { QueryClient } from "@tanstack/react-query"

// 模块级持有 QueryClient,供非组件代码(store.logout / onUnauth 兜底登出)清空缓存。
// 否则同一标签页内 A 登出、B 登入后,未按 user 命名的 key(messages/docs/agentSkills/registry)
// 可能先渲染出 A 的缓存再被网络刷新覆盖 —— 一次跨租户数据闪现。
let _qc: QueryClient | null = null
export const setQueryClient = (qc: QueryClient) => {
  _qc = qc
}
export const clearQueryCache = () => {
  _qc?.clear()
}
