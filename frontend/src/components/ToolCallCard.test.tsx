import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { ToolCallCard } from "./ToolCallCard"

describe("ToolCallCard", () => {
  it("write_file: shows the path, hides content by default (no escaped blob)", () => {
    render(
      <ToolCallCard
        call={{ id: "c1", name: "write_file", arguments: { path: "qsort.py", content: "def f():\n    return 1" } }}
        result={{ call_id: "c1", content: "wrote qsort.py", is_error: false }}
      />,
    )
    expect(screen.getByText("write_file")).toBeInTheDocument()
    expect(screen.getByText("qsort.py")).toBeInTheDocument()
    // 写入内容默认折叠,不应直接出现在 DOM(避免一坨转义字符串)
    expect(screen.queryByText(/def f\(\)/)).not.toBeInTheDocument()
  })

  it("bash: command 是摘要;成功输出默认折叠,点头部展开", () => {
    render(
      <ToolCallCard
        call={{ id: "c2", name: "bash", arguments: { command: "ls -la" } }}
        result={{ call_id: "c2", content: "total 0", is_error: false }}
      />,
    )
    expect(screen.getByText("bash")).toBeInTheDocument()
    expect(screen.getByText("ls -la")).toBeInTheDocument()
    expect(screen.queryByText("total 0")).not.toBeInTheDocument() // 成功默认折叠
    fireEvent.click(screen.getByRole("button"))
    expect(screen.getByText("total 0")).toBeInTheDocument() // 点头部展开
  })

  it("失败结果默认展开(无需点击即可见)", () => {
    render(
      <ToolCallCard
        call={{ id: "c3", name: "bash", arguments: { command: "boom" } }}
        result={{ call_id: "c3", content: "exit 1: nope", is_error: true }}
      />,
    )
    expect(screen.getByText("exit 1: nope")).toBeInTheDocument()
  })

  it("失败默认展开后可手动收起(收起不被错误态强制反弹)", () => {
    render(
      <ToolCallCard
        call={{ id: "c5", name: "bash", arguments: { command: "boom" } }}
        result={{ call_id: "c5", content: "exit 1: nope", is_error: true }}
      />,
    )
    expect(screen.getByText("exit 1: nope")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button"))
    expect(screen.queryByText("exit 1: nope")).not.toBeInTheDocument()
  })

  it("no result yet → renders the running state without crashing", () => {
    const { container } = render(
      <ToolCallCard call={{ id: "c4", name: "bash", arguments: { command: "sleep 1" } }} />,
    )
    expect(container.textContent).toContain("sleep 1")
  })
})

describe("ToolCallCard pending(参数生成中)", () => {
  it("显示路径与计数,无展开按钮与结果区", () => {
    render(
      <ToolCallCard
        call={{ id: "c9", name: "write_file", arguments: {} }}
        progress={{ argsChars: 12345, lines: 340, path: "src/big.py" }}
      />,
    )
    expect(screen.getByText("write_file")).toBeInTheDocument()
    expect(screen.getByText("src/big.py")).toBeInTheDocument()
    expect(screen.getByText("已生成 12.3k 字符 · 约 340 行")).toBeInTheDocument()
    expect(screen.queryByRole("button")).not.toBeInTheDocument()
  })

  it("单行小参数:不显示行数", () => {
    render(
      <ToolCallCard
        call={{ id: "c8", name: "bash", arguments: {} }}
        progress={{ argsChars: 42, lines: 1, path: "" }}
      />,
    )
    expect(screen.getByText("已生成 42 字符")).toBeInTheDocument()
  })
})
