import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { useStore } from "../store"
import { AuthGate } from "./AuthGate"

vi.mock("../api/client", () => ({
  api: { login: vi.fn(), register: vi.fn() },
}))

describe("AuthGate", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useStore.setState({ user: null, userId: null })
  })

  it("renders login mode and toggles to register", () => {
    render(<AuthGate />)
    expect(screen.getByText("登录到你的工作区")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "注册" })) // toggle link in login mode
    expect(screen.getByText("创建一个新账户")).toBeInTheDocument()
  })

  it("submits login → api.login + setAuth", async () => {
    const user = { id: "u1", email: "a@e.com" }
    vi.mocked(api.login).mockResolvedValue(user)
    render(<AuthGate />)
    fireEvent.change(screen.getByPlaceholderText("you@example.com"), { target: { value: "a@e.com" } })
    fireEvent.change(screen.getByPlaceholderText("••••••••"), { target: { value: "password123" } })
    fireEvent.click(screen.getByRole("button", { name: "登录" }))
    await waitFor(() => expect(api.login).toHaveBeenCalledWith("a@e.com", "password123"))
    await waitFor(() => expect(useStore.getState().user).toEqual(user))
  })

  it("submits register when in register mode", async () => {
    const user = { id: "u2", email: "b@e.com" }
    vi.mocked(api.register).mockResolvedValue(user)
    render(<AuthGate />)
    fireEvent.click(screen.getByRole("button", { name: "注册" })) // login → register
    fireEvent.change(screen.getByPlaceholderText("you@example.com"), { target: { value: "b@e.com" } })
    fireEvent.change(screen.getByPlaceholderText("至少 8 位"), { target: { value: "password123" } })
    fireEvent.click(screen.getByRole("button", { name: "注册" })) // now the submit button
    await waitFor(() => expect(api.register).toHaveBeenCalledWith("b@e.com", "password123"))
  })

  it("shows inline error when register password too short", async () => {
    render(<AuthGate />)
    fireEvent.click(screen.getByRole("button", { name: "注册" })) // login → register
    fireEvent.change(screen.getByPlaceholderText("you@example.com"), { target: { value: "b@e.com" } })
    fireEvent.change(screen.getByPlaceholderText("至少 8 位"), { target: { value: "short" } })
    fireEvent.click(screen.getByRole("button", { name: "注册" }))
    expect(await screen.findByText("密码至少 8 位")).toBeInTheDocument()
    expect(api.register).not.toHaveBeenCalled()
  })
})
