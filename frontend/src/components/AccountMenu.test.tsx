import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { useStore } from "../store"
import { AccountMenu } from "./AccountMenu"

vi.mock("../api/client", () => ({
  api: { logout: vi.fn().mockResolvedValue(undefined) },
}))

describe("AccountMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useStore.setState({ user: { id: "u1", email: "alice@example.com" }, userId: "u1" })
  })

  it("触发器是圆头像(不直接显示邮箱);菜单内含邮箱行 / Provider Keys / 登出", () => {
    render(<AccountMenu />)
    expect(screen.queryByText("alice@example.com")).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "账户" }))
    expect(screen.getByText("alice@example.com")).toBeInTheDocument()
    expect(screen.getByText("登出")).toBeInTheDocument()
    expect(screen.getByText("Provider Keys")).toBeInTheDocument()
    // 工作区文件入口已迁往主区顶栏(TopBar),菜单里不应再有
    expect(screen.queryByText("工作区文件")).not.toBeInTheDocument()
  })

  it("logs out: calls api.logout then clears the store user", async () => {
    render(<AccountMenu />)
    fireEvent.click(screen.getByRole("button", { name: "账户" })) // open menu
    fireEvent.click(screen.getByText("登出"))
    await waitFor(() => expect(api.logout).toHaveBeenCalled())
    await waitFor(() => expect(useStore.getState().user).toBeNull())
  })
})
