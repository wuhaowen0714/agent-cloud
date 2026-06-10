import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api } from "../../api/client"
import { useStore } from "../../store"
import { ModelMenu } from "./ModelMenu"

const AGENT = {
  id: "a1",
  user_id: "u1",
  name: "A",
  model: "gpt-x",
  provider: "openai",
  thinking_level: null,
  enabled_tools: [],
  permissions: {},
  key_ref: null,
}

function setup(value = "DeepSeek-V4-Pro") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  useStore.setState({ userId: "u1" })
  // 只 mock fetch(不预填缓存):useQuery 挂载即取,避免「预填后被 refetch 覆盖」的 flaky。
  vi.spyOn(api, "listModels").mockResolvedValue([{ id: "m1", model: "my-model", created_at: "" }])
  vi.spyOn(api, "listAgents").mockResolvedValue([AGENT as never])
  const onChange = vi.fn()
  render(
    <QueryClientProvider client={qc}>
      <ModelMenu value={value} onChange={onChange} />
    </QueryClientProvider>,
  )
  return { onChange }
}

const openMenu = () => fireEvent.click(screen.getByRole("button", { name: /DeepSeek-V4-Pro/ }))

afterEach(() => {
  useStore.setState({ userId: null })
  vi.restoreAllMocks()
})

describe("ModelMenu", () => {
  it("列出预设+在用+自定义,勾选当前", async () => {
    setup()
    openMenu()
    expect(await screen.findByRole("option", { name: /my-model/ })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: /gpt-x/ })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: /GLM-5\.1/ })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: /DeepSeek-V4-Pro/ })).toHaveAttribute(
      "aria-selected",
      "true",
    )
  })

  it("点击选项回调 onChange 并关闭", async () => {
    const { onChange } = setup()
    openMenu()
    fireEvent.click(await screen.findByRole("option", { name: /DeepSeek-V4-Flash/ }))
    expect(onChange).toHaveBeenCalledWith("DeepSeek-V4-Flash")
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
  })

  it("添加模型:即加即选", async () => {
    const spy = vi
      .spyOn(api, "addModel")
      .mockResolvedValue({ id: "m9", model: "new-m", created_at: "" })
    const { onChange } = setup()
    openMenu()
    fireEvent.click(await screen.findByText("添加模型…"))
    const input = screen.getByPlaceholderText("模型名,Enter 确认")
    fireEvent.change(input, { target: { value: " new-m " } })
    fireEvent.keyDown(input, { key: "Enter" })
    await waitFor(() => expect(spy).toHaveBeenCalledWith("new-m"))
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("new-m"))
  })

  it("自定义条目可删,删除不触发 onChange", async () => {
    const del = vi.spyOn(api, "deleteModel").mockResolvedValue(undefined)
    const { onChange } = setup()
    openMenu()
    await screen.findByRole("option", { name: /my-model/ })
    fireEvent.click(screen.getByLabelText("删除 my-model"))
    await waitFor(() => expect(del).toHaveBeenCalledWith("m1"))
    expect(onChange).not.toHaveBeenCalled()
  })
})
