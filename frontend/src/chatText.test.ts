import { describe, expect, it } from "vitest"
import { parseUserMessage, stripWorkspaceImageMarkdown } from "./chatText"

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

describe("parseUserMessage", () => {
  const MARKER =
    "[Uploaded file(s) in the workspace — read with read_file, or edit images with edit_image]"

  it("摘出附件路径,正文只留用户文本", () => {
    const { body, attachments } = parseUserMessage(`总结一下这个文档\n\n${MARKER}\nupload/report.pdf`)
    expect(body).toBe("总结一下这个文档")
    expect(attachments).toEqual(["upload/report.pdf"])
  })

  it("多个附件(图片+文件混合)", () => {
    const { attachments } = parseUserMessage(`看这些\n\n${MARKER}\nupload/a.png\nupload/b.pdf`)
    expect(attachments).toEqual(["upload/a.png", "upload/b.pdf"])
  })

  it("仅附件无正文:body 为空", () => {
    const { body, attachments } = parseUserMessage(`\n\n${MARKER}\nupload/data.xlsx`)
    expect(body).toBe("")
    expect(attachments).toEqual(["upload/data.xlsx"])
  })

  it("含空格的文件名(upload/ 前缀)仍解析", () => {
    const { attachments } = parseUserMessage(`x\n\n${MARKER}\nupload/my report final.pdf`)
    expect(attachments).toEqual(["upload/my report final.pdf"])
  })

  it("技能 marker:摘出技能名,正文留用户文本", () => {
    const { body, skills } = parseUserMessage("帮我整理\n\n[请使用技能:文档整理]")
    expect(body).toBe("帮我整理")
    expect(skills).toEqual(["文档整理"])
  })

  it("多个技能(每技能一行)+ 附件混合", () => {
    const r = parseUserMessage(
      `做个表\n\n[请使用技能:xlsx]\n[请使用技能:图表]\n\n${MARKER}\nupload/data.csv`,
    )
    expect(r.body).toBe("做个表")
    expect(r.skills).toEqual(["xlsx", "图表"])
    expect(r.attachments).toEqual(["upload/data.csv"])
  })

  // 对抗审查 High:用户正文句中内联打 [请使用技能:x] 不能被吞成 chip + 从正文删除(整行锚定)。
  it("正文句中内联 [请使用技能:x] 不被吞", () => {
    const t = "这个功能怎么用?我打 [请使用技能:foo] 会怎样"
    expect(parseUserMessage(t)).toEqual({ body: t, attachments: [], skills: [] })
  })

  // 对抗审查 M1:技能名含逗号/顿号也不切碎(每技能独占一行,不靠分隔符 split)。
  it("技能名含逗号也不切碎", () => {
    const { skills } = parseUserMessage("x\n\n[请使用技能:数据,分析]")
    expect(skills).toEqual(["数据,分析"])
  })

  it("仅技能无正文:body 空", () => {
    const { body, skills } = parseUserMessage("[请使用技能:brainstorm]")
    expect(body).toBe("")
    expect(skills).toEqual(["brainstorm"])
  })

  it("兼容早期 Attached image marker", () => {
    const t =
      "这是什么\n\n[Attached image(s) in the workspace — use edit_image to edit them]\nupload/cat.png"
    expect(parseUserMessage(t)).toEqual({ body: "这是什么", attachments: ["upload/cat.png"], skills: [] })
  })

  it("无 marker:原样返回,无附件", () => {
    expect(parseUserMessage("你好")).toEqual({ body: "你好", attachments: [], skills: [] })
  })

  // 对抗审查 H1:用户正文恰好含 marker 样式文本,后接真实正文(非路径)→ 不能吞正文
  it("正文含 marker 样式但后接正文(非路径):不解析,原样保留正文", () => {
    const t = `The error is:\n${MARKER}\nplease help me fix line 3 and 4`
    expect(parseUserMessage(t)).toEqual({ body: t, attachments: [], skills: [] })
  })

  // M1:fork 回填可能产生多段 marker;末段为真,中间 marker 行不应混进附件
  it("多段 marker:只收工作区路径行,过滤残留 marker 行", () => {
    const t = `问题\n\n${MARKER}\nupload/a.png\n\n${MARKER}\nupload/b.png`
    expect(parseUserMessage(t).attachments).toEqual(["upload/a.png", "upload/b.png"])
  })

  // M2:CRLF 也要正常解析(否则 marker + 裸路径原样暴露)
  it("CRLF 换行也能解析", () => {
    const { body, attachments } = parseUserMessage(`总结\r\n\r\n${MARKER}\r\nupload/x.pdf`)
    expect(body).toBe("总结")
    expect(attachments).toEqual(["upload/x.pdf"])
  })

  it("marker 后混入非路径行:整体不解析,保留正文", () => {
    const t = `hi\n\n${MARKER}\nupload/ok.png\nrandom note here`
    expect(parseUserMessage(t)).toEqual({ body: t, attachments: [], skills: [] })
  })
})
