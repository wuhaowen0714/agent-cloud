import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { api } from "../../api/client"
import type { FileEntry } from "../../types"
import { FilePreview } from "./FilePreview"

beforeAll(() => {
  // jsdom 没有 revokeObjectURL;组件 cleanup 会调它
  URL.revokeObjectURL ??= () => {}
})

// 用户报障场景:中文名 txt(此前后端 Content-Disposition 塞原始 UTF-8 → 500,
// 预览与下载双挂;下载还因裸 await 静默无反应)。
const entry = {
  name: "小说_最后一盏灯.txt",
  path: "小说_最后一盏灯.txt",
  is_dir: false,
  size: 9,
  mtime: 0,
} as FileEntry

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const mdEntry = {
  name: "README.md",
  path: "README.md",
  is_dir: false,
  size: 20,
  mtime: 0,
} as FileEntry
const htmlEntry = {
  name: "hello_world.html",
  path: "hello_world.html",
  is_dir: false,
  size: 30,
  mtime: 0,
} as FileEntry

const stubFetchText = (text: string) =>
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ text: () => Promise.resolve(text) }),
  )

describe("FilePreview 渲染(spec 2026-06-10-preview-render)", () => {
  it("markdown 渲染为富文本,可切回源码", async () => {
    vi.spyOn(api, "previewUrl").mockResolvedValue("blob:fake-md")
    stubFetchText("# 大标题\n\n- 列表项")
    render(<FilePreview entry={mdEntry} onClose={() => {}} />)
    expect(await screen.findByRole("heading", { name: "大标题" })).toBeInTheDocument()
    fireEvent.click(screen.getByText("源码"))
    expect(screen.getByText(/# 大标题/)).toBeInTheDocument() // <pre> 原文
    fireEvent.click(screen.getByText("渲染"))
    expect(await screen.findByRole("heading", { name: "大标题" })).toBeInTheDocument()
  })

  it("html 走沙箱 iframe:allow-scripts 且绝不含 allow-same-origin", async () => {
    vi.spyOn(api, "previewUrl").mockResolvedValue("blob:fake-html")
    stubFetchText("<h1>hi</h1>")
    render(<FilePreview entry={htmlEntry} onClose={() => {}} />)
    const frame = await screen.findByTitle("hello_world.html")
    expect(frame.tagName).toBe("IFRAME")
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts")
    expect(frame.getAttribute("src")).toBe("blob:fake-html")
    fireEvent.click(screen.getByText("源码"))
    expect(screen.getByText("<h1>hi</h1>")).toBeInTheDocument()
  })
})

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

const imgEntry = {
  name: "img_abc.png",
  path: "media/picture/img_abc.png",
  is_dir: false,
  size: 1024,
  mtime: 0,
} as FileEntry

describe("FilePreview 加载反馈(大图)", () => {
  it("图片未就绪显示加载占位,就绪后显示图(不再静默空白)", async () => {
    let resolve: (u: string) => void = () => {}
    vi.spyOn(api, "previewUrl").mockReturnValue(
      new Promise<string>((r) => {
        resolve = r
      }),
    )
    render(<FilePreview entry={imgEntry} onClose={() => {}} />)
    // blob 拉取期间给占位,而不是空白(用户曾以为卡住)
    expect(screen.getByText("加载中…")).toBeInTheDocument()
    expect(screen.queryByRole("img")).toBeNull()
    resolve("blob:fake-img")
    expect(await screen.findByRole("img")).toHaveAttribute("src", "blob:fake-img")
  })

  it("下载点击后立即给「下载中…」反馈", async () => {
    vi.spyOn(api, "previewUrl").mockResolvedValue("blob:img")
    let resolveDl: (u: string) => void = () => {}
    vi.spyOn(api, "downloadUrl").mockReturnValue(
      new Promise<string>((r) => {
        resolveDl = r
      }),
    )
    render(<FilePreview entry={imgEntry} onClose={() => {}} />)
    await screen.findByRole("img") // 等预览图就绪
    fireEvent.click(screen.getByText("下载"))
    expect(await screen.findByText("下载中…")).toBeInTheDocument()
    resolveDl("blob:dl") // 收尾,避免悬挂 promise
  })
})
