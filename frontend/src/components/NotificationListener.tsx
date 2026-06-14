import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { api } from "../api/client"
import { useStore } from "../store"
import type { Notification as AppNotification } from "../types"

const PERM_DISMISS_KEY = "ac.notifPermDismissed"

// 安全取 DOM Notification 构造器(jsdom / 老浏览器可能没有 → 优雅降级:只弹应用内 toast)。
function getNotif(): typeof Notification | undefined {
  return typeof window !== "undefined" && "Notification" in window ? window.Notification : undefined
}

// 全局通知监听器(挂 App,已登录树内):轮询未送达通知 → OS 通知 + 应用内 toast → mark-delivered。
// 仅"标签页开着时"送达(spec 2026-06-14)。
export function NotificationListener() {
  const userId = useStore((s) => s.userId)
  const setSession = useStore((s) => s.setSession)
  const qc = useQueryClient()
  const [toasts, setToasts] = useState<AppNotification[]>([])
  const [permDismissed, setPermDismissed] = useState(
    () => localStorage.getItem(PERM_DISMISS_KEY) === "1",
  )
  const seen = useRef<Set<string>>(new Set()) // 防多轮轮询/重渲染重复处理同一条

  const { data: pending = [] } = useQuery({
    queryKey: ["notifications", userId],
    queryFn: () => api.listNotifications(),
    enabled: !!userId,
    refetchInterval: 15000,
  })

  useEffect(() => {
    const fresh = pending.filter((n) => !seen.current.has(n.id))
    if (fresh.length === 0) return
    const N = getNotif()
    for (const n of fresh) {
      seen.current.add(n.id)
      if (N && N.permission === "granted") {
        try {
          new N(n.title, { body: n.body })
        } catch {
          /* 某些上下文构造会抛;忽略,应用内 toast 仍在 */
        }
      }
    }
    setToasts((prev) => [...prev, ...fresh])
    void api
      .markNotificationsDelivered(fresh.map((n) => n.id))
      .then(() => qc.invalidateQueries({ queryKey: ["notifications", userId] }))
      .catch(() => {
        // mark-delivered 失败:用户已看到 toast/OS 通知,这些 id 留在 seen 不在本会话重弹;
        // 服务端仍为未送达,刷新页面(seen 重置)会重试标记。best-effort,吞掉 rejection。
      })
  }, [pending, userId, qc])

  const dismiss = (id: string) => setToasts((t) => t.filter((x) => x.id !== id))
  const openOrigin = (n: AppNotification) => {
    if (n.origin_session_id) setSession(n.origin_session_id)
    dismiss(n.id)
  }
  const closeBanner = () => {
    setPermDismissed(true)
    localStorage.setItem(PERM_DISMISS_KEY, "1")
  }
  const askPerm = () => {
    const N = getNotif()
    if (N) void N.requestPermission().finally(closeBanner)
    else closeBanner()
  }

  const N = getNotif()
  const showBanner = !!userId && !!N && N.permission === "default" && !permDismissed

  return (
    <>
      {showBanner && (
        <div className="fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm shadow-pop">
          <span className="text-slate-600">开启系统提醒?定时任务到点会弹通知</span>
          <button
            type="button"
            className="rounded-lg bg-brand-500 px-3 py-1 text-xs font-medium text-white hover:bg-brand-600"
            onClick={askPerm}
          >
            开启
          </button>
          <button
            type="button"
            aria-label="关闭"
            className="text-slate-400 hover:text-slate-600"
            onClick={closeBanner}
          >
            ✕
          </button>
        </div>
      )}
      <div
        className="fixed bottom-4 right-4 z-50 flex flex-col gap-2"
        role="region"
        aria-label="通知"
      >
        {toasts.map((n) => (
          <div
            key={n.id}
            role="alert"
            className="flex w-72 items-start gap-2 rounded-xl border border-slate-200 bg-white p-3 shadow-pop"
          >
            <button
              type="button"
              className="min-w-0 flex-1 text-left"
              onClick={() => openOrigin(n)}
            >
              <div className="truncate text-sm font-medium text-slate-800">{n.title}</div>
              <div className="mt-0.5 text-xs text-slate-500">{n.body}</div>
            </button>
            <button
              type="button"
              aria-label={`关闭 ${n.title}`}
              className="shrink-0 text-slate-400 hover:text-slate-600"
              onClick={() => dismiss(n.id)}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </>
  )
}
