import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { useStore } from "../store"
import type { Notification as AppNotification } from "../types"
import { NotificationListener } from "./NotificationListener"

const notif = (over: Partial<AppNotification> = {}): AppNotification => ({
  id: "n1",
  title: "喝药提醒",
  body: "该喝药了",
  origin_session_id: null,
  created_at: "2026-06-14T08:00:00+00:00",
  ...over,
})

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

beforeEach(() => {
  useStore.setState({ userId: "u1" })
  localStorage.clear()
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("NotificationListener", () => {
  it("轮询到通知 → 弹 toast + 调 markNotificationsDelivered", async () => {
    vi.stubGlobal("Notification", Object.assign(vi.fn(), { permission: "denied" }))
    vi.spyOn(api, "listNotifications").mockResolvedValue([notif()])
    const mark = vi.spyOn(api, "markNotificationsDelivered").mockResolvedValue(undefined)
    render(wrap(<NotificationListener />))
    expect(await screen.findByText("喝药提醒")).toBeInTheDocument()
    expect(screen.getByText("该喝药了")).toBeInTheDocument()
    await waitFor(() => expect(mark).toHaveBeenCalledWith(["n1"]))
  })

  it("已授权 → 构造 OS Notification", async () => {
    const NotifMock = Object.assign(vi.fn(), { permission: "granted" })
    vi.stubGlobal("Notification", NotifMock)
    vi.spyOn(api, "listNotifications").mockResolvedValue([notif()])
    vi.spyOn(api, "markNotificationsDelivered").mockResolvedValue(undefined)
    render(wrap(<NotificationListener />))
    await waitFor(() =>
      expect(NotifMock).toHaveBeenCalledWith("喝药提醒", { body: "该喝药了" }),
    )
  })

  it("permission=default → 显示开启 banner,点击调 requestPermission", async () => {
    const reqPerm = vi.fn().mockResolvedValue("granted")
    vi.stubGlobal(
      "Notification",
      Object.assign(vi.fn(), { permission: "default", requestPermission: reqPerm }),
    )
    vi.spyOn(api, "listNotifications").mockResolvedValue([])
    render(wrap(<NotificationListener />))
    fireEvent.click(await screen.findByRole("button", { name: "开启" }))
    await waitFor(() => expect(reqPerm).toHaveBeenCalled())
  })

  it("不支持 Notification 时只弹 toast,不崩", async () => {
    vi.stubGlobal("Notification", undefined)
    vi.spyOn(api, "listNotifications").mockResolvedValue([notif()])
    vi.spyOn(api, "markNotificationsDelivered").mockResolvedValue(undefined)
    render(wrap(<NotificationListener />))
    expect(await screen.findByText("喝药提醒")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "开启" })).toBeNull()
  })

  it("mark-delivered 失败:toast 仍展示,不抛未处理 rejection", async () => {
    vi.stubGlobal("Notification", undefined)
    vi.spyOn(api, "listNotifications").mockResolvedValue([notif()])
    const mark = vi
      .spyOn(api, "markNotificationsDelivered")
      .mockRejectedValue(new Error("network"))
    render(wrap(<NotificationListener />))
    expect(await screen.findByText("喝药提醒")).toBeInTheDocument()
    await waitFor(() => expect(mark).toHaveBeenCalledWith(["n1"]))
  })
})
