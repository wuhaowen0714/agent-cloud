import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { SettingsNav } from "./SettingsNav"

describe("SettingsNav", () => {
  it("渲染 4 个 tab,点击回调对应 id", () => {
    const onSelect = vi.fn()
    render(<SettingsNav tab="agent" onSelect={onSelect} />)
    for (const name of ["Agent", "技能", "记忆", "Provider Keys"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument()
    }
    fireEvent.click(screen.getByRole("button", { name: "记忆" }))
    expect(onSelect).toHaveBeenCalledWith("memory")
  })

  it("当前 tab 高亮(aria-current)", () => {
    render(<SettingsNav tab="skills" onSelect={() => {}} />)
    expect(screen.getByRole("button", { name: "技能" })).toHaveAttribute("aria-current", "true")
  })
})
