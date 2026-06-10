import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { RowMenu } from "./RowMenu"

const open = () => fireEvent.click(screen.getByRole("button", { name: "更多操作" }))

describe("RowMenu", () => {
  it("普通项点击即执行并关闭", async () => {
    const onSelect = vi.fn()
    render(<RowMenu ariaLabel="更多操作" items={[{ label: "重命名", onSelect }]} />)
    open()
    fireEvent.click(screen.getByRole("menuitem", { name: "重命名" }))
    await waitFor(() => expect(onSelect).toHaveBeenCalled())
    expect(screen.queryByRole("menu")).not.toBeInTheDocument()
  })

  it("带确认项需点两次:第一次变确认文案且不执行", async () => {
    const onSelect = vi.fn()
    render(
      <RowMenu
        ariaLabel="更多操作"
        items={[{ label: "删除", danger: true, confirmLabel: "确认删除?", onSelect }]}
      />,
    )
    open()
    fireEvent.click(screen.getByRole("menuitem", { name: "删除" }))
    expect(onSelect).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole("menuitem", { name: "确认删除?" }))
    await waitFor(() => expect(onSelect).toHaveBeenCalled())
  })

  it("onSelect 拒绝 → 原位提示「进行中,无法删除」", async () => {
    const onSelect = vi.fn().mockRejectedValue(new Error("409"))
    render(
      <RowMenu
        ariaLabel="更多操作"
        items={[{ label: "删除", danger: true, confirmLabel: "确认删除?", onSelect }]}
      />,
    )
    open()
    fireEvent.click(screen.getByRole("menuitem", { name: "删除" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "确认删除?" }))
    expect(await screen.findByText("进行中,无法删除")).toBeInTheDocument()
  })
})
