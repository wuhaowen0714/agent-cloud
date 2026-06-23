import { describe, expect, it } from "vitest"
import { formatSize, isHiddenEntry, previewKind, splitBreadcrumb } from "./files"

describe("formatSize", () => {
  it("formats bytes/KB/MB", () => {
    expect(formatSize(512)).toBe("512 B")
    expect(formatSize(2048)).toBe("2.0 KB")
    expect(formatSize(5 * 1024 * 1024)).toBe("5.0 MB")
  })
})

describe("splitBreadcrumb", () => {
  it("always starts at the workspace root", () => {
    expect(splitBreadcrumb("")).toEqual([{ name: "工作区", path: "" }])
  })
  it("accumulates nested paths", () => {
    expect(splitBreadcrumb("a/b")).toEqual([
      { name: "工作区", path: "" }, { name: "a", path: "a" }, { name: "b", path: "a/b" },
    ])
  })
})

describe("previewKind", () => {
  it("detects images by extension", () => {
    expect(previewKind({ name: "p.png", size: 9_000_000 })).toBe("image")
  })
  it("treats small non-images as text and large as download", () => {
    expect(previewKind({ name: "a.txt", size: 100 })).toBe("text")
    expect(previewKind({ name: "big.bin", size: 5_000_000 })).toBe("download")
  })
  it("markdown/html 走渲染类(同受 1MB 上限)", () => {
    expect(previewKind({ name: "README.md", size: 100 })).toBe("markdown")
    expect(previewKind({ name: "n.markdown", size: 100 })).toBe("markdown")
    expect(previewKind({ name: "hello_world.html", size: 100 })).toBe("html")
    expect(previewKind({ name: "h.htm", size: 100 })).toBe("html")
    expect(previewKind({ name: "big.md", size: 2_000_000 })).toBe("download")
    expect(previewKind({ name: "big.html", size: 2_000_000 })).toBe("download")
  })
  it("pdf 原生渲染、office 文档后端抽文本,都在 1MB 上限之前判定", () => {
    expect(previewKind({ name: "report.pdf", size: 100 })).toBe("pdf")
    expect(previewKind({ name: "r.docx", size: 100 })).toBe("doc")
    expect(previewKind({ name: "slides.pptx", size: 100 })).toBe("doc")
    expect(previewKind({ name: "sheet.xlsx", size: 100 })).toBe("doc")
    expect(previewKind({ name: "macro.xlsm", size: 100 })).toBe("doc")
    // 关键:文档体积常 >1MB,绝不能掉进 download(extract 内部另有 25MB 闸兜底)
    expect(previewKind({ name: "big.pdf", size: 9_000_000 })).toBe("pdf")
    expect(previewKind({ name: "big.xlsx", size: 9_000_000 })).toBe("doc")
  })
})

describe("isHiddenEntry", () => {
  it("点目录隐藏(沙箱基础设施),点文件保留(用户内容,与 @ 索引政策一致)", () => {
    expect(isHiddenEntry({ name: ".home", is_dir: true })).toBe(true)
    expect(isHiddenEntry({ name: ".npm-global", is_dir: true })).toBe(true)
    expect(isHiddenEntry({ name: ".env.example", is_dir: false })).toBe(false)
    expect(isHiddenEntry({ name: "src", is_dir: true })).toBe(false)
    expect(isHiddenEntry({ name: "a.txt", is_dir: false })).toBe(false)
  })
})
