import { render, screen } from "@testing-library/react"
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

  it("bash: command is the summary, output is the result", () => {
    render(
      <ToolCallCard
        call={{ id: "c2", name: "bash", arguments: { command: "ls -la" } }}
        result={{ call_id: "c2", content: "total 0", is_error: false }}
      />,
    )
    expect(screen.getByText("bash")).toBeInTheDocument()
    expect(screen.getByText("ls -la")).toBeInTheDocument()
    expect(screen.getByText("total 0")).toBeInTheDocument()
  })

  it("renders an error result", () => {
    render(
      <ToolCallCard
        call={{ id: "c3", name: "bash", arguments: { command: "boom" } }}
        result={{ call_id: "c3", content: "exit 1: nope", is_error: true }}
      />,
    )
    expect(screen.getByText("exit 1: nope")).toBeInTheDocument()
  })

  it("no result yet → renders the running state without crashing", () => {
    const { container } = render(
      <ToolCallCard call={{ id: "c4", name: "bash", arguments: { command: "sleep 1" } }} />,
    )
    expect(container.textContent).toContain("sleep 1")
  })
})
