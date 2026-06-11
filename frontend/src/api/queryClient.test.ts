import { QueryClient } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { refreshSessionsLater } from "./queryClient"

describe("refreshSessionsLater", () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it("延迟到点才 invalidate sessions,且恰一次", () => {
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, "invalidateQueries")
    refreshSessionsLater(qc, 3000)
    expect(spy).not.toHaveBeenCalled()
    vi.advanceTimersByTime(2999)
    expect(spy).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(spy).toHaveBeenCalledExactlyOnceWith({ queryKey: ["sessions"] })
  })
})
