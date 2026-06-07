import type { TurnEvent } from "../types"

/** 把任意切分的 SSE 文本喂进来,逐个 data: 事件回调。返回一个 feed(chunk) 函数。 */
export function parseSSE(onEvent: (e: TurnEvent) => void): (chunk: string) => void {
  let buf = ""
  return (chunk: string) => {
    buf += chunk
    let sep: number
    // SSE 事件以空行(\n\n)分隔
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const block = buf.slice(0, sep)
      buf = buf.slice(sep + 2)
      for (const line of block.split("\n")) {
        const trimmed = line.trim()
        if (trimmed.startsWith("data:")) {
          const payload = trimmed.slice("data:".length).trim()
          if (payload) {
            try {
              onEvent(JSON.parse(payload) as TurnEvent)
            } catch {
              // 跳过畸形事件:别让单个坏块 reject done → 整回合失败。
            }
          }
        }
      }
    }
  }
}

/** POST /turn/stream 并把 SSE 事件流式回调;返回可中断的 AbortController。 */
export function streamTurn(
  sessionId: string,
  content: string,
  onEvent: (e: TurnEvent) => void,
): { done: Promise<void>; abort: () => void } {
  const ctrl = new AbortController()
  const done = (async () => {
    const res = await fetch(`/api/sessions/${sessionId}/turn/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
      signal: ctrl.signal,
    })
    if (!res.ok || !res.body) {
      const body = await res.text().catch(() => "")
      throw new Error(`turn stream failed: ${res.status} ${body}`)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    const feed = parseSSE(onEvent)
    for (;;) {
      const { done: rdone, value } = await reader.read()
      if (rdone) break
      feed(decoder.decode(value, { stream: true }))
    }
  })()
  return { done, abort: () => ctrl.abort() }
}

/** GET 续看进行中回合:204 → null(没有在跑);否则补播+实时,返回可中断句柄。 */
export async function resumeTurn(
  sessionId: string,
  onEvent: (e: TurnEvent) => void,
): Promise<{ done: Promise<void>; abort: () => void } | null> {
  const ctrl = new AbortController()
  const res = await fetch(`/api/sessions/${sessionId}/turn/stream`, { signal: ctrl.signal })
  if (res.status === 204 || !res.body) return null
  if (!res.ok) throw new Error(`resume failed: ${res.status}`)
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  const feed = parseSSE(onEvent)
  const done = (async () => {
    for (;;) {
      const { done: rdone, value } = await reader.read()
      if (rdone) break
      feed(decoder.decode(value, { stream: true }))
    }
  })()
  return { done, abort: () => ctrl.abort() }
}

/** 主动停止服务端正在跑的回合(幂等)。 */
export async function cancelTurn(sessionId: string): Promise<void> {
  await fetch(`/api/sessions/${sessionId}/turn/cancel`, { method: "POST" })
}
