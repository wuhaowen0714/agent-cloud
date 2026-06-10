import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { SettingGroup } from "./SettingGroup"
import { SettingRow } from "./SettingRow"

describe("SettingGroup / SettingRow", () => {
  it("渲染分组标题与行内 label + 控件", () => {
    render(
      <SettingGroup label="基本">
        <SettingRow label="名称" hint="给它起个名">
          <input aria-label="名称输入" />
        </SettingRow>
      </SettingGroup>,
    )
    expect(screen.getByText("基本")).toBeInTheDocument()
    expect(screen.getByText("名称")).toBeInTheDocument()
    expect(screen.getByText("给它起个名")).toBeInTheDocument()
    expect(screen.getByLabelText("名称输入")).toBeInTheDocument()
  })

  it("block 行也渲染 label + children", () => {
    render(
      <SettingRow label="工具" block>
        <button>bash</button>
      </SettingRow>,
    )
    expect(screen.getByText("工具")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "bash" })).toBeInTheDocument()
  })
})
