import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryPanel } from "./MemoryPanel"

vi.mock("../../api/client", () => ({
  api: {
    getMemory: vi
      .fn()
      .mockResolvedValue({ scope: "user", owner_id: "u1", content: "- likes tea", version: 1 }),
    putMemory: vi
      .fn()
      .mockResolvedValue({ scope: "user", owner_id: "u1", content: "- likes coffee", version: 2 }),
    clearMemory: vi
      .fn()
      .mockResolvedValue({ scope: "user", owner_id: "u1", content: "", version: 3 }),
  },
}))

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

describe("MemoryPanel", () => {
  beforeEach(() => vi.clearAllMocks())

  it("loads the current block and saves edits", async () => {
    const { api } = await import("../../api/client")
    render(wrap(<MemoryPanel scope="user" />))
    const ta = await screen.findByDisplayValue("- likes tea")
    fireEvent.change(ta, { target: { value: "- likes coffee" } })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))
    await waitFor(() =>
      expect(api.putMemory).toHaveBeenCalledWith("user", "- likes coffee", undefined),
    )
  })

  it("clears the block", async () => {
    const { api } = await import("../../api/client")
    render(wrap(<MemoryPanel scope="user" />))
    await screen.findByDisplayValue("- likes tea")
    fireEvent.click(screen.getByRole("button", { name: "清空" }))
    await waitFor(() => expect(api.clearMemory).toHaveBeenCalledWith("user", undefined))
  })

  it("passes agentId for agent scope", async () => {
    const { api } = await import("../../api/client")
    render(wrap(<MemoryPanel scope="agent" agentId="ag1" />))
    await screen.findByDisplayValue("- likes tea")
    fireEvent.click(screen.getByRole("button", { name: "保存" }))
    await waitFor(() =>
      expect(api.putMemory).toHaveBeenCalledWith("agent", "- likes tea", "ag1"),
    )
  })
})
