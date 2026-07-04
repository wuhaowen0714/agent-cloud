import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { parseEdits, ToolCallCard } from "./ToolCallCard"

describe("parseEdits", () => {
  it("解析合法 edits,丢弃非法项", () => {
    expect(
      parseEdits({
        edits: [
          { old_text: "a", new_text: "b" },
          { old_text: 1, new_text: "x" }, // 非法丢
          "junk",
        ],
      }),
    ).toEqual([{ old_text: "a", new_text: "b" }])
    expect(parseEdits({})).toEqual([])
  })
})

describe("ToolCallCard edit diff", () => {
  it("edit 卡展开渲染红绿 diff(- 旧行 / + 新行)", async () => {
    const { container } = render(
      <ToolCallCard
        call={{
          id: "c1",
          name: "edit",
          arguments: {
            path: "notes.md",
            edits: [{ old_text: "old line", new_text: "new line" }],
          },
        }}
        result={{ call_id: "c1", content: "ok", is_error: false }}
      />,
    )
    screen.getByRole("button").click()
    // 等 React 状态更新
    await new Promise((r) => setTimeout(r, 0))
    expect(container.textContent).toContain("old line")
    expect(container.textContent).toContain("new line")
    expect(container.textContent).toContain("notes.md")
  })
})
