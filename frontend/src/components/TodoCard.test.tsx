import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import type { Block } from "../blocks"
import { parseTodoItems, TodoCard } from "./TodoCard"
import { TurnBlocks } from "./TurnBlocks"

describe("parseTodoItems", () => {
  it("解析合法 items,丢弃非法项(不可信模型输出容错)", () => {
    const items = parseTodoItems({
      items: [
        { content: "查资料", status: "completed" },
        { content: "写初稿", status: "in_progress" },
        { content: "", status: "pending" }, // 空 content 丢
        { content: "x", status: "done" }, // 非法 status 丢
        "not-an-object",
      ],
    })
    expect(items).toEqual([
      { content: "查资料", status: "completed" },
      { content: "写初稿", status: "in_progress" },
    ])
  })

  it("items 缺失/非数组 → 空", () => {
    expect(parseTodoItems({})).toEqual([])
    expect(parseTodoItems({ items: "x" })).toEqual([])
  })
})

describe("TodoCard", () => {
  it("渲染进度计数与三种状态", () => {
    render(
      <TodoCard
        items={[
          { content: "查资料", status: "completed" },
          { content: "写初稿", status: "in_progress" },
          { content: "排版", status: "pending" },
        ]}
      />,
    )
    expect(screen.getByText("任务清单")).toBeInTheDocument()
    expect(screen.getByText("1/3")).toBeInTheDocument()
    expect(screen.getByText("写初稿")).toBeInTheDocument()
  })
})

describe("TurnBlocks todo 原位刷新", () => {
  const todoBlock = (id: string, items: unknown): Block => ({
    kind: "tool",
    id,
    call: { id, name: "todo", arguments: { items } },
    result: { call_id: id, content: "ok", is_error: false },
  })

  it("多次 todo 调用只渲染一张卡(首现位置),内容取最新一次", () => {
    const blocks: Block[] = [
      todoBlock("t1", [
        { content: "a", status: "pending" },
        { content: "b", status: "pending" },
      ]),
      { kind: "text", id: "x", text: "干活中" },
      todoBlock("t2", [
        { content: "a", status: "completed" },
        { content: "b", status: "in_progress" },
      ]),
    ]
    render(<TurnBlocks blocks={blocks} />)
    // 只有一张清单卡,进度是最新的 1/2
    expect(screen.getAllByText("任务清单")).toHaveLength(1)
    expect(screen.getByText("1/2")).toBeInTheDocument()
  })

  it("非 todo 工具卡不受影响", () => {
    const blocks: Block[] = [
      {
        kind: "tool",
        id: "c1",
        call: { id: "c1", name: "bash", arguments: { command: "ls" } },
      },
    ]
    render(<TurnBlocks blocks={blocks} />)
    expect(screen.queryByText("任务清单")).not.toBeInTheDocument()
  })
})
