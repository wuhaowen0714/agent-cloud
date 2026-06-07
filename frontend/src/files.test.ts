import { describe, expect, it } from "vitest"
import { formatSize, previewKind, splitBreadcrumb } from "./files"

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
})
