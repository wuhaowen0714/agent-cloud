import { act, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { MessageActions } from "./MessageActions"

afterEach(() => {
  Object.assign(navigator, { clipboard: undefined })
  // @ts-expect-error 清掉测试装上的 execCommand mock
  delete document.execCommand
  vi.useRealTimers()
  vi.restoreAllMocks()
})

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

  it("每个按钮带自绘 tooltip 文案(替代原生 title:无 1s 悬停门槛)", () => {
    render(<MessageActions text="hi" onRollback={() => {}} onFork={() => {}} />)
    expect(screen.getByText("复制")).toBeInTheDocument()
    expect(screen.getByText("回滚到此处(删除其后消息)")).toBeInTheDocument()
    expect(screen.getByText("Fork:从这里开新会话分支")).toBeInTheDocument()
    // 不再用原生 title(会和自绘 tooltip 叠出两个)
    expect(screen.getByRole("button", { name: "复制" })).not.toHaveAttribute("title")
  })

  it("clipboard API 可用:复制走 writeText 并显示「已复制」", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    render(<MessageActions text="hello world" />)
    fireEvent.click(screen.getByRole("button", { name: "复制" }))
    expect(writeText).toHaveBeenCalledWith("hello world")
    expect(await screen.findByText("已复制")).toBeInTheDocument()
  })

  it("HTTP 部署(clipboard undefined):退回 execCommand 仍能复制并反馈", async () => {
    Object.assign(navigator, { clipboard: undefined })
    document.execCommand = vi.fn(() => true)
    render(<MessageActions text="copy me" />)
    fireEvent.click(screen.getByRole("button", { name: "复制" }))
    expect(await screen.findByText("已复制")).toBeInTheDocument()
    expect(document.execCommand).toHaveBeenCalledWith("copy")
  })

  it("两条路都失败 → 显示「复制失败」", async () => {
    Object.assign(navigator, { clipboard: undefined })
    document.execCommand = vi.fn(() => false)
    render(<MessageActions text="copy me" />)
    fireEvent.click(screen.getByRole("button", { name: "复制" }))
    expect(await screen.findByText("复制失败")).toBeInTheDocument()
  })

  it("同结果连点:反馈计时被重置而非沿用旧定时器(审查 I2)", async () => {
    vi.useFakeTimers()
    Object.assign(navigator, { clipboard: undefined })
    document.execCommand = vi.fn(() => false) // 恒失败 → 两次都是「复制失败」(同值 setState)
    render(<MessageActions text="x" />)
    const btn = screen.getByRole("button", { name: "复制" })
    fireEvent.click(btn)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0) // flush copyText promise
    })
    expect(screen.getByText("复制失败")).toBeInTheDocument()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500)
    })
    fireEvent.click(btn) // t=1.5s 重试
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200) // t=1.7s:首次的 1.6s 定时器已过点
    })
    expect(screen.getByText("复制失败")).toBeInTheDocument() // 仍显示 → 计时确被重置
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500) // 第二次的 1.6s 走完
    })
    expect(screen.queryByText("复制失败")).not.toBeInTheDocument()
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
