import { describe, expect, it } from "vitest"
import { atTokenAt, filterPaths } from "./fileRef"

describe("atTokenAt", () => {
  it("句首 @ 触发", () => {
    expect(atTokenAt("@", 1)).toEqual({ start: 0, query: "" })
    expect(atTokenAt("@src", 4)).toEqual({ start: 0, query: "src" })
  })

  it("空白后 @ 触发(空格/换行)", () => {
    expect(atTokenAt("看下 @app", 7)).toEqual({ start: 3, query: "app" })
    expect(atTokenAt("hi\n@x", 5)).toEqual({ start: 3, query: "x" })
  })

  it("邮箱(@ 前是非空白)不触发", () => {
    expect(atTokenAt("mail me a@b.com", 15)).toBeNull()
  })

  it("光标在词中间只取 @ 到光标", () => {
    expect(atTokenAt("@abcd", 3)).toEqual({ start: 0, query: "ab" })
  })

  it("光标在 @ 之前(词外)不触发", () => {
    expect(atTokenAt("@x", 0)).toBeNull()
  })

  it("无 @ / 词内第二个 @ → null", () => {
    expect(atTokenAt("hello", 5)).toBeNull()
    expect(atTokenAt("@a@b", 4)).toBeNull()
  })

  it("中文 query", () => {
    expect(atTokenAt("@小说", 3)).toEqual({ start: 0, query: "小说" })
  })

  it("@ 词已结束(光标在后续词上)不触发", () => {
    expect(atTokenAt("@src/a.py 然后", 12)).toBeNull()
  })
})

describe("filterPaths", () => {
  const paths = ["src/App.tsx", "src/main.tsx", "docs/读我.md", "README.md"]

  it("大小写不敏感子串(路径任意位置)", () => {
    expect(filterPaths(paths, "app")).toEqual(["src/App.tsx"])
    expect(filterPaths(paths, "READ")).toEqual(["README.md"])
  })

  it("中文命中", () => {
    expect(filterPaths(paths, "读我")).toEqual(["docs/读我.md"])
  })

  it("空 query 全量保序", () => {
    expect(filterPaths(paths, "")).toEqual(paths)
  })

  it("max 截断(默认 20)", () => {
    const many = Array.from({ length: 30 }, (_, i) => `f${i}.txt`)
    expect(filterPaths(many, "", 3)).toEqual(["f0.txt", "f1.txt", "f2.txt"])
    expect(filterPaths(many, "")).toHaveLength(20)
  })

  it("无命中 → 空表", () => {
    expect(filterPaths(paths, "zzz")).toEqual([])
  })
})
