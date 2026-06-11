import { beforeEach, describe, expect, it } from "vitest"
import { useStore } from "./store"

const s = () => useStore.getState()

const reset = () =>
  useStore.setState({
    user: null,
    userId: null,
    agentId: null,
    sessionId: null,
    live: null,
    compactions: {},
    fileDrawerOpen: false,
    settingsOpen: false,
  })

describe("store 压缩状态(per-session)", () => {
  beforeEach(reset)

  it("start → running,finish → result,clear → 移除", () => {
    s().startCompaction("A")
    expect(s().compactions.A).toEqual({ phase: "running" })
    s().finishCompaction("A", "compacted")
    expect(s().compactions.A).toEqual({ phase: "result", result: "compacted" })
    s().clearCompaction("A")
    expect(s().compactions.A).toBeUndefined()
  })

  it("多会话互不影响", () => {
    s().startCompaction("A")
    s().finishCompaction("B", "error")
    expect(s().compactions.A).toEqual({ phase: "running" })
    expect(s().compactions.B).toEqual({ phase: "result", result: "error" })
  })

  it("切换会话不清压缩状态(跨会话存活),但仍清 live", () => {
    s().startCompaction("A")
    useStore.setState({ live: { userText: "x", sessionId: "A", startedAt: "", blocks: [], status: "streaming" } })
    s().setSession("B")
    expect(s().compactions.A).toEqual({ phase: "running" })
    expect(s().live).toBeNull()
  })

  it("logout 清空压缩状态", () => {
    s().startCompaction("A")
    s().logout()
    expect(s().compactions).toEqual({})
  })
})
