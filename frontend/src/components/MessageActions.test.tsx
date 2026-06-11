import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { MessageActions } from "./MessageActions"

describe("MessageActions", () => {
  it("有 onRollback/onFork → 复制/回滚/fork 三个;否则仅复制", () => {
    const { rerender } = render(<MessageActions text="hi" onRollback={() => {}} onFork={() => {}} />)
    expect(screen.getByRole("button", { name: "复制" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "回滚到此处" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Fork 新会话" })).toBeInTheDocument()

    rerender(<MessageActions text="ans" />)
    expect(screen.getByRole("button", { name: "复制" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "回滚到此处" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Fork 新会话" })).not.toBeInTheDocument()
  })

  it("每个按钮有 title 提示(hover 可见,解释图标含义)", () => {
    render(<MessageActions text="hi" onRollback={() => {}} onFork={() => {}} />)
    expect(screen.getByRole("button", { name: "复制" })).toHaveAttribute("title", "复制")
    expect(screen.getByRole("button", { name: "回滚到此处" })).toHaveAttribute(
      "title",
      "回滚到此处(删除其后消息)",
    )
    expect(screen.getByRole("button", { name: "Fork 新会话" })).toHaveAttribute(
      "title",
      "Fork:从这里开新会话分支",
    )
  })

  it("复制调 clipboard.writeText", () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    render(<MessageActions text="hello world" />)
    fireEvent.click(screen.getByRole("button", { name: "复制" }))
    expect(writeText).toHaveBeenCalledWith("hello world")
  })

  it("回滚/fork 触发对应回调", () => {
    const onRollback = vi.fn()
    const onFork = vi.fn()
    render(<MessageActions text="q" onRollback={onRollback} onFork={onFork} />)
    fireEvent.click(screen.getByRole("button", { name: "回滚到此处" }))
    fireEvent.click(screen.getByRole("button", { name: "Fork 新会话" }))
    expect(onRollback).toHaveBeenCalledOnce()
    expect(onFork).toHaveBeenCalledOnce()
  })
})
