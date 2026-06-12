import { describe, expect, it } from "vitest"
import { stripWorkspaceImageMarkdown } from "./chatText"

describe("stripWorkspaceImageMarkdown", () => {
  it("移除工作区相对路径图(已由工具卡片展示,正文渲染裸路径会破损)", () => {
    const t = "已为你生成图片!\n\n![柴犬](media/picture/img_abc.png)\n\n一只金黄柴犬。"
    const out = stripWorkspaceImageMarkdown(t)
    expect(out).not.toContain("![")
    expect(out).toContain("已为你生成图片!")
    expect(out).toContain("一只金黄柴犬。")
  })

  it("保留外部 http(s) 图片(能正常加载,不误伤)", () => {
    const t = "看这个 ![logo](https://example.com/logo.png) 图标"
    expect(stripWorkspaceImageMarkdown(t)).toContain("https://example.com/logo.png")
  })

  it("行内相对路径图也移除", () => {
    const out = stripWorkspaceImageMarkdown("see ![x](./out.png) here")
    expect(out).not.toContain("![")
    expect(out).toContain("see")
    expect(out).toContain("here")
  })

  it("带 title 的相对路径图也移除", () => {
    const out = stripWorkspaceImageMarkdown('![a](media/picture/x.png "标题")')
    expect(out).toBe("")
  })

  it("无图正文原样返回(快速短路)", () => {
    const t = "纯文字回复,没有图片。"
    expect(stripWorkspaceImageMarkdown(t)).toBe(t)
  })

  it("不误伤普通 markdown 链接", () => {
    const t = "见 [文档](media/docs/readme.md) 说明"
    expect(stripWorkspaceImageMarkdown(t)).toBe(t)
  })
})
