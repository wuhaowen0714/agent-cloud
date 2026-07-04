import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { ToolCallCard } from "./ToolCallCard"

const call = { id: "c1", name: "bash", arguments: { command: "rm -rf build" } }

describe("危险操作确认按钮", () => {
  it("被拦结果(含批准码)→ 渲染按钮,点击发送确认消息", () => {
    const onApprove = vi.fn()
    render(
      <ToolCallCard
        call={call}
        result={{
          call_id: "c1",
          content: "⚠️ 已拦截可能有破坏性的操作:递归强制删除(rm -rf)(批准码 abcd1234abcd1234)。",
          is_error: true,
        }}
        onApprove={onApprove}
      />,
    )
    fireEvent.click(screen.getByRole("button", { name: "允许执行并继续" }))
    expect(onApprove).toHaveBeenCalledWith("允许执行该操作(批准码 abcd1234abcd1234)")
  })

  it("普通错误(无批准码)/ 未传 onApprove → 不渲染按钮", () => {
    const { rerender } = render(
      <ToolCallCard
        call={call}
        result={{ call_id: "c1", content: "command not found", is_error: true }}
        onApprove={() => {}}
      />,
    )
    expect(screen.queryByRole("button", { name: "允许执行并继续" })).toBeNull()
    rerender(
      <ToolCallCard
        call={call}
        result={{ call_id: "c1", content: "批准码 abcd1234abcd1234", is_error: true }}
      />,
    )
    expect(screen.queryByRole("button", { name: "允许执行并继续" })).toBeNull()
  })
})
