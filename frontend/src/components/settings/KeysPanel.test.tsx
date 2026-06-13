import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { useStore } from "../../store"
import { KeysPanel } from "./KeysPanel"

vi.mock("../../api/client", () => ({
  api: {
    listCredentials: vi.fn().mockResolvedValue([
      {
        id: "c1",
        name: "openrouter",
        base_url: "https://or/v1",
        masked: "sk-…1234",
        models: ["gpt-4o"],
        created_at: "",
      },
    ]),
    createCredential: vi.fn().mockResolvedValue({
      id: "c2",
      name: "x",
      base_url: "",
      masked: "sk-…9999",
      models: [],
      created_at: "",
    }),
    deleteCredential: vi.fn().mockResolvedValue(undefined),
  },
}))

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

describe("KeysPanel", () => {
  beforeEach(() => useStore.setState({ userId: "u1" }))

  it("lists existing credentials by mask (never plaintext)", async () => {
    render(wrap(<KeysPanel />))
    // 掩码与 base_url 现在同在一行 hint 里,用包含匹配(仍验证显示掩码、非明文)
    expect(await screen.findByText(/sk-…1234/)).toBeInTheDocument()
    expect(screen.getByText("openrouter")).toBeInTheDocument()
  })

  it("submits a new credential", async () => {
    const { api } = await import("../../api/client")
    render(wrap(<KeysPanel />))
    fireEvent.change(screen.getByPlaceholderText("如 openrouter"), { target: { value: "x" } })
    fireEvent.change(screen.getByPlaceholderText("sk-…"), { target: { value: "sk-9999" } })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))
    await waitFor(() =>
      expect(api.createCredential).toHaveBeenCalledWith({
        name: "x",
        base_url: "",
        api_key: "sk-9999",
        models: [],
      }),
    )
  })
})
