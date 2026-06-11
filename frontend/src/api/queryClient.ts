import type { QueryClient } from "@tanstack/react-query"
import type { Session } from "../types"

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

// 首回合标题在服务端异步生成(一次 LLM 调用,常 >3s,首回合带工具调用更久)。轮询刷新
// sessions 直到该会话拿到 title 或到上限——单次延迟刷常赶在标题生成完之前,就会出现
// 「第一条不出标题、第二条才出」。invalidate 很轻(一个 GET /sessions),拿到即停;
// maxAttempts 兜底(标题 LLM 失败时 title 永远 null,不能无限轮询)。
export function pollSessionTitle(
  qc: QueryClient,
  userId: string,
  sessionId: string,
  { intervalMs = 2000, maxAttempts = 8 }: { intervalMs?: number; maxAttempts?: number } = {},
) {
  let n = 0
  const tick = async () => {
    n += 1
    // 精确 key:active 的 sessions query(Sidebar 订阅)会被 await 到 refetch 完成,
    // 随后 getQueryData 读到的就是新值。
    await qc.invalidateQueries({ queryKey: ["sessions", userId] })
    const got = qc
      .getQueryData<Session[]>(["sessions", userId])
      ?.find((s) => s.id === sessionId)?.title
    if (got || n >= maxAttempts) return
    setTimeout(tick, intervalMs)
  }
  setTimeout(tick, intervalMs)
}
