import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { api } from "../../api/client"
import { useStore } from "../../store"
import { ModelMenu } from "./ModelMenu"

function setup(model = "DeepSeek-V4-Pro", credentialId: string | null = null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  useStore.setState({ userId: "u1" })
  vi.spyOn(api, "getPlatformModels").mockResolvedValue({
    models: ["DeepSeek-V4-Pro", "DeepSeek-V4-Flash"],
    default: "DeepSeek-V4-Pro",
  })
  vi.spyOn(api, "listCredentials").mockResolvedValue([
    {
      id: "c1",
      name: "openrouter",
      base_url: "",
      masked: "sk-…1",
      models: ["gpt-4o"],
      created_at: "",
    },
  ] as never)
  const onChange = vi.fn()
  render(
    <QueryClientProvider client={qc}>
      <ModelMenu model={model} credentialId={credentialId} onChange={onChange} />
    </QueryClientProvider>,
  )
  return { onChange }
}

afterEach(() => {
  useStore.setState({ userId: null })
  vi.restoreAllMocks()
})

describe("ModelMenu(provider + model 两栏)", () => {
  it("provider 栏列出平台 sophnet + BYOK provider", async () => {
    setup()
    fireEvent.click(screen.getByRole("button", { name: "provider" }))
    expect(await screen.findByRole("option", { name: /openrouter/ })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: /sophnet/ })).toBeInTheDocument()
  })

  it("model 栏列出当前 provider 的模型,勾选当前", async () => {
    setup()
    fireEvent.click(screen.getByRole("button", { name: "model" }))
    expect(await screen.findByRole("option", { name: /DeepSeek-V4-Flash/ })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: /DeepSeek-V4-Pro/ })).toHaveAttribute(
      "aria-selected",
      "true",
    )
  })

  it("选 model → onChange(model, 当前 credentialId)", async () => {
    const { onChange } = setup()
    fireEvent.click(screen.getByRole("button", { name: "model" }))
    fireEvent.click(await screen.findByRole("option", { name: /DeepSeek-V4-Flash/ }))
    expect(onChange).toHaveBeenCalledWith("DeepSeek-V4-Flash", null)
  })

  it("切 provider 到 BYOK → 取其首个 model + 该 credentialId", async () => {
    const { onChange } = setup()
    fireEvent.click(screen.getByRole("button", { name: "provider" }))
    fireEvent.click(await screen.findByRole("option", { name: /openrouter/ }))
    expect(onChange).toHaveBeenCalledWith("gpt-4o", "c1")
  })
})
