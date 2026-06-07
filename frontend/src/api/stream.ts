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
          if (payload) onEvent(JSON.parse(payload) as TurnEvent)
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
