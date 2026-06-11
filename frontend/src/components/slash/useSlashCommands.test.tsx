import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api, HttpError } from "../../api/client"
import { useStore } from "../../store"
import { useSlashCommands } from "./useSlashCommands"

const ui = { notify: vi.fn(), showStatus: vi.fn(), showHelp: vi.fn() }

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient()
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

const render = () => renderHook(() => useSlashCommands(ui), { wrapper })
const comp = (sid: string) => useStore.getState().compactions[sid]

afterEach(() => {
  useStore.setState({ sessionId: null, compactions: {} })
  vi.restoreAllMocks()
})

describe("useSlashCommands.compact 写入 store(per-session)", () => {
  it("成功:running → result(compacted)", async () => {
    useStore.setState({ sessionId: "s1", compactions: {} })
    let resolve!: (v: { compacted: boolean }) => void
    vi.spyOn(api, "compactSession").mockReturnValue(new Promise((r) => (resolve = r)))
    const { result } = render()
    let p!: Promise<void>
    act(() => {
      p = result.current.compact()
    })
    expect(comp("s1")).toEqual({ phase: "running" })
    await act(async () => {
      resolve({ compacted: true })
      await p
    })
    expect(comp("s1")).toEqual({ phase: "result", result: "compacted" })
  })

  it("compacted:false → nothing", async () => {
    useStore.setState({ sessionId: "s1", compactions: {} })
    vi.spyOn(api, "compactSession").mockResolvedValue({ compacted: false })
    const { result } = render()
    await act(async () => {
      await result.current.compact()
    })
    expect(comp("s1")).toEqual({ phase: "result", result: "nothing" })
  })

  it("409 → busy,其他错误 → error", async () => {
    useStore.setState({ sessionId: "s1", compactions: {} })
    vi.spyOn(api, "compactSession").mockRejectedValue(new HttpError(409, "busy"))
    const { result } = render()
    await act(async () => {
      await result.current.compact()
    })
    expect(comp("s1")).toEqual({ phase: "result", result: "busy" })

    useStore.setState({ sessionId: "s1", compactions: {} })
    vi.spyOn(api, "compactSession").mockRejectedValue(new Error("boom"))
    await act(async () => {
      await result.current.compact()
    })
    expect(comp("s1")).toEqual({ phase: "result", result: "error" })
  })

  it("捕获发起时的 sid:运行中切到别的 session,仍写回原 session", async () => {
    useStore.setState({ sessionId: "s1", compactions: {} })
    let resolve!: (v: { compacted: boolean }) => void
    vi.spyOn(api, "compactSession").mockReturnValue(new Promise((r) => (resolve = r)))
    const { result } = render()
    let p!: Promise<void>
    act(() => {
      p = result.current.compact()
    })
    // 压缩进行中切到别的会话
    act(() => {
      useStore.setState({ sessionId: "s2" })
    })
    await act(async () => {
      resolve({ compacted: true })
      await p
    })
    expect(comp("s1")).toEqual({ phase: "result", result: "compacted" })
    expect(comp("s2")).toBeUndefined() // 绝不串到 s2
  })
})
