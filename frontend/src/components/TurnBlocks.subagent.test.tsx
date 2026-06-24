import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import type { Block } from "../blocks"
import { TurnBlocks } from "./TurnBlocks"

const sub = (over: Partial<Extract<Block, { kind: "subagent" }>> = {}): Block => ({
  kind: "subagent",
  id: "sub-1",
  description: "搜世界杯",
  blocks: [
    { kind: "tool", id: "c1", call: { id: "c1", name: "web_search", arguments: {} } },
    { kind: "text", id: "x", text: "子结果文本" },
  ],
  running: false,
  ok: true,
  ...over,
})

describe("SubagentCard(经 TurnBlocks)", () => {
  it("运行中:强制展开 + 显示运行中 + 内部可见", () => {
    render(<TurnBlocks blocks={[sub({ running: true })]} streaming />)
    expect(screen.getByText("子 agent")).toBeInTheDocument()
    expect(screen.getByText("· 搜世界杯")).toBeInTheDocument()
    expect(screen.getByText("运行中…")).toBeInTheDocument()
    expect(screen.getByText("子结果文本")).toBeInTheDocument() // 运行中强制展开
  })

  it("完成:默认折叠(内部隐藏)+ 显示步数,点头展开", () => {
    render(<TurnBlocks blocks={[sub({ running: false, ok: true })]} />)
    expect(screen.getByText(/1 步/)).toBeInTheDocument() // 1 个工具调用 = 1 步
    expect(screen.queryByText("子结果文本")).toBeNull() // 折叠,内部隐藏
    fireEvent.click(screen.getByRole("button"))
    expect(screen.getByText("子结果文本")).toBeInTheDocument() // 展开后可见
  })

  it("失败:显示 ✗ 标记", () => {
    render(<TurnBlocks blocks={[sub({ running: false, ok: false })]} />)
    expect(screen.getByText(/✗/)).toBeInTheDocument()
  })

  it("历史态(内部无工具、steps=0):只显示状态、不显示「0 步」", () => {
    render(
      <TurnBlocks
        blocks={[
          sub({ running: false, ok: true, blocks: [{ kind: "text", id: "r", text: "结果" }] }),
        ]}
      />,
    )
    expect(screen.getByText("✓")).toBeInTheDocument()
    expect(screen.queryByText(/步/)).toBeNull()
  })
})
