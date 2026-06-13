import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { UserBubble } from "./Bubble"

const MARKER =
  "[Uploaded file(s) in the workspace — read with read_file, or edit images with edit_image]"

describe("UserBubble 附件渲染", () => {
  it("文件附件:显示文件名 chip + 正文,不显示内部 marker 与裸路径", () => {
    render(<UserBubble text={`总结一下这个文档\n\n${MARKER}\nupload/report.pdf`} />)
    expect(screen.getByText("总结一下这个文档")).toBeInTheDocument()
    expect(screen.getByText("report.pdf")).toBeInTheDocument()
    expect(screen.queryByText(/Uploaded file/)).not.toBeInTheDocument()
    expect(screen.queryByText(/upload\//)).not.toBeInTheDocument()
  })

  it("仅附件无正文:只显示 chip", () => {
    render(<UserBubble text={`\n\n${MARKER}\nupload/data.xlsx`} />)
    expect(screen.getByText("data.xlsx")).toBeInTheDocument()
    expect(screen.queryByText(/Uploaded file/)).not.toBeInTheDocument()
  })

  it("无附件:正文原样", () => {
    render(<UserBubble text="你好世界" />)
    expect(screen.getByText("你好世界")).toBeInTheDocument()
  })

  it("正文恰好含 marker 样式文本:原样显示,不吞正文(对抗审查 H1)", () => {
    render(<UserBubble text={`报错信息:\n${MARKER}\n请帮我看看第三行`} />)
    expect(screen.getByText(/请帮我看看第三行/)).toBeInTheDocument()
  })
})
