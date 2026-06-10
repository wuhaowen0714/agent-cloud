import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api } from "../../api/client"
import type { FileEntry } from "../../types"
import { FilePreview } from "./FilePreview"

// 用户报障场景:中文名 txt(此前后端 Content-Disposition 塞原始 UTF-8 → 500,
// 预览与下载双挂;下载还因裸 await 静默无反应)。
const entry = {
  name: "小说_最后一盏灯.txt",
  path: "小说_最后一盏灯.txt",
  is_dir: false,
  size: 9,
  mtime: 0,
} as FileEntry

afterEach(() => vi.restoreAllMocks())

describe("FilePreview 失败路径", () => {
  it("预览拉取失败 → 显示「无法预览」提示", async () => {
    vi.spyOn(api, "previewUrl").mockRejectedValue(new Error("500"))
    render(<FilePreview entry={entry} onClose={() => {}} />)
    expect(await screen.findByText("无法预览,请下载查看。")).toBeInTheDocument()
  })

  it("下载失败不静默:点击后有提示而非毫无反应", async () => {
    vi.spyOn(api, "previewUrl").mockRejectedValue(new Error("500"))
    const dl = vi.spyOn(api, "downloadUrl").mockRejectedValue(new Error("500"))
    render(<FilePreview entry={entry} onClose={() => {}} />)
    fireEvent.click(screen.getByText("下载"))
    expect(await screen.findByText("无法预览,请下载查看。")).toBeInTheDocument()
    expect(dl).toHaveBeenCalledWith(entry.path)
  })
})
