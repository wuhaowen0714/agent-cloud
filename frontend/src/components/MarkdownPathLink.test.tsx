import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { Markdown } from "./Markdown"

describe("Markdown 工作区路径链接", () => {
  it("inline code 命中 → 可点按钮,点击回调;未命中/块级不变", () => {
    const onOpen = vi.fn()
    const resolve = (t: string) =>
      t === "documents/a.md" ? { path: "documents/a.md", isDir: false } : null
    render(
      <Markdown resolvePath={resolve} onOpenPath={onOpen}>
        {"看 `documents/a.md` 和 `other.md`\n\n```js\nconst documents = 1\n```"}
      </Markdown>,
    )
    const btn = screen.getByRole("button", { name: "documents/a.md" })
    fireEvent.click(btn)
    expect(onOpen).toHaveBeenCalledWith({ path: "documents/a.md", isDir: false })
    expect(screen.queryByRole("button", { name: "other.md" })).toBeNull() // 未命中保持 code
  })

  it("不传解析器 → 原行为(纯 code,无按钮)", () => {
    render(<Markdown>{"`documents/a.md`"}</Markdown>)
    expect(screen.queryByRole("button")).toBeNull()
  })
})
