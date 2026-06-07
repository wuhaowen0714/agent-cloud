import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import type { Block } from "../blocks"
import { TurnBlocks } from "./TurnBlocks"

describe("TurnBlocks", () => {
  it("renders blocks in chronological order (text → tool → text), not bucketed", () => {
    const blocks: Block[] = [
      { kind: "text", id: "t1", text: "first" },
      { kind: "tool", id: "c1", call: { id: "c1", name: "bash", arguments: { command: "ls" } }, result: { call_id: "c1", content: "a.txt", is_error: false } },
      { kind: "text", id: "t2", text: "second" },
    ]
    const { container } = render(<TurnBlocks blocks={blocks} />)
    const text = container.textContent ?? ""
    // 顺序断言:正文1 在工具之前,工具在正文2 之前
    expect(text.indexOf("first")).toBeLessThan(text.indexOf("bash"))
    expect(text.indexOf("bash")).toBeLessThan(text.indexOf("second"))
    expect(text).toContain("a.txt") // 工具结果配对显示在卡片内
  })

  it("auto-expands the last thinking block while streaming", () => {
    const blocks: Block[] = [{ kind: "thinking", id: "th1", text: "reasoning here" }]
    render(<TurnBlocks blocks={blocks} streaming />)
    // active → 默认展开,思考文本可见
    expect(screen.getByText("reasoning here")).toBeInTheDocument()
  })

  it("keeps a non-last thinking block collapsed by default", () => {
    const blocks: Block[] = [
      { kind: "thinking", id: "th1", text: "old reasoning" },
      { kind: "text", id: "t1", text: "answer" },
    ]
    render(<TurnBlocks blocks={blocks} streaming />)
    // 思考不是最后一块 → 折叠,正文照常显示
    expect(screen.queryByText("old reasoning")).not.toBeInTheDocument()
    expect(screen.getByText("answer")).toBeInTheDocument()
  })
})
