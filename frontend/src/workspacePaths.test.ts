import { describe, expect, it } from "vitest"
import { resolveWorkspacePath } from "./workspacePaths"

const index = [
  "documents/python-study-plan/README.md",
  "documents/python-study-plan/week1-2-basics/README.md",
  "documents/report/final.docx",
  "notes.txt",
  "uploads/pic.png",
]

describe("resolveWorkspacePath", () => {
  it("精确路径 → 文件", () => {
    expect(resolveWorkspacePath("documents/report/final.docx", index)).toEqual({
      path: "documents/report/final.docx",
      isDir: false,
    })
  })

  it("目录前缀 → 目录(带不带尾斜杠都认)", () => {
    expect(resolveWorkspacePath("documents/python-study-plan/", index)).toEqual({
      path: "documents/python-study-plan",
      isDir: true,
    })
    expect(resolveWorkspacePath("documents", index)).toEqual({ path: "documents", isDir: true })
  })

  it("裸文件名唯一 → 链接;多义 → 不链接", () => {
    expect(resolveWorkspacePath("final.docx", index)).toEqual({
      path: "documents/report/final.docx",
      isDir: false,
    })
    expect(resolveWorkspacePath("notes.txt", index)).toEqual({ path: "notes.txt", isDir: false })
    expect(resolveWorkspacePath("README.md", index)).toBeNull() // 两处都有,宁可不跳
  })

  it("不存在 / 外部 URL / 绝对路径 / 含空白 / 普通代码 → 不链接", () => {
    expect(resolveWorkspacePath("ghost.md", index)).toBeNull()
    expect(resolveWorkspacePath("https://example.com/a.md", index)).toBeNull()
    expect(resolveWorkspacePath("/etc/passwd", index)).toBeNull()
    expect(resolveWorkspacePath("pip install requests", index)).toBeNull()
    expect(resolveWorkspacePath("", index)).toBeNull()
  })
})
