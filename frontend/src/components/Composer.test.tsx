import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { Composer } from "./Composer"

describe("Composer", () => {
  it("shows 发送 when idle and calls onSend", () => {
    const onSend = vi.fn()
    render(<Composer disabled={false} onSend={onSend} onStop={() => {}} />)
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "hi" } })
    fireEvent.click(screen.getByText("发送"))
    expect(onSend).toHaveBeenCalledWith("hi")
  })

  it("shows 停止 while streaming and calls onStop", () => {
    const onStop = vi.fn()
    render(<Composer disabled onSend={() => {}} onStop={onStop} />)
    expect(screen.queryByText("发送")).not.toBeInTheDocument()
    fireEvent.click(screen.getByText("停止"))
    expect(onStop).toHaveBeenCalled()
  })
})
