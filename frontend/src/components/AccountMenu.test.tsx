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

  it("shows the email and opens the menu", () => {
    render(<AccountMenu />)
    expect(screen.getByText("alice@example.com")).toBeInTheDocument()
    fireEvent.click(screen.getByText("alice@example.com"))
    expect(screen.getByText("登出")).toBeInTheDocument()
    expect(screen.getByText("工作区文件")).toBeInTheDocument()
  })

  it("logs out: calls api.logout then clears the store user", async () => {
    render(<AccountMenu />)
    fireEvent.click(screen.getByText("alice@example.com")) // open menu
    fireEvent.click(screen.getByText("登出"))
    await waitFor(() => expect(api.logout).toHaveBeenCalled())
    await waitFor(() => expect(useStore.getState().user).toBeNull())
  })
})
