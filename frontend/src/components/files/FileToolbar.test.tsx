import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api } from "../../api/client"
import { FileToolbar } from "./FileToolbar"

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

afterEach(() => vi.restoreAllMocks())

describe("FileToolbar 文件夹上传", () => {
  it("有「上传文件夹」按钮与 webkitdirectory 选择器,选中即触发上传", async () => {
    const up = vi.spyOn(api, "uploadFiles").mockResolvedValue([])
    render(wrap(<FileToolbar path="" onChanged={() => {}} />))
    expect(screen.getByRole("button", { name: "↑ 上传文件夹" })).toBeInTheDocument()

    const dirInput = screen.getByLabelText("选择要上传的文件夹")
    expect(dirInput).toHaveAttribute("webkitdirectory")

    const f = new File(["x"], "a.txt", { type: "text/plain" })
    fireEvent.change(dirInput, { target: { files: [f] } })
    await waitFor(() => expect(up).toHaveBeenCalled())
    expect(up.mock.calls[0][1]).toHaveLength(1)
  })
})
