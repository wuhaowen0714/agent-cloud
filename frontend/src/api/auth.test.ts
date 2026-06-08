import { afterEach, describe, expect, it, vi } from "vitest"
import { authedFetch, getAccess, refreshAccess, setAccess, setOnUnauth } from "./auth"

afterEach(() => {
  vi.unstubAllGlobals()
  setAccess(null)
  setOnUnauth(() => {})
})

describe("refreshAccess (single-flight)", () => {
  it("dedupes concurrent calls into one /auth/refresh POST", async () => {
    const f = vi.fn(async () => new Response(JSON.stringify({ access_token: "tok1" }), { status: 200 }))
    vi.stubGlobal("fetch", f)
    const [a, b] = await Promise.all([refreshAccess(), refreshAccess()])
    expect(a).toBe("tok1")
    expect(b).toBe("tok1")
    expect(f).toHaveBeenCalledTimes(1) // 单飞:并发只打一次
    expect(getAccess()).toBe("tok1")
  })

  it("returns null and clears the access token when refresh fails", async () => {
    setAccess("stale")
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 401 })))
    expect(await refreshAccess()).toBeNull()
    expect(getAccess()).toBeNull()
  })
})

describe("authedFetch", () => {
  it("refreshes once on 401 then retries with the new token", async () => {
    setAccess("old")
    const urls: string[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit = {}) => {
        urls.push(String(url))
        if (url === "/api/auth/refresh")
          return new Response(JSON.stringify({ access_token: "new" }), { status: 200 })
        const auth = (init.headers as Record<string, string>)?.Authorization
        return auth === "Bearer new" ? new Response("ok", { status: 200 }) : new Response(null, { status: 401 })
      }),
    )
    const res = await authedFetch("/api/x")
    expect(res.status).toBe(200)
    expect(urls).toEqual(["/api/x", "/api/auth/refresh", "/api/x"])
  })

  it("calls onUnauth on a terminal 401 (refresh also fails)", async () => {
    setAccess("old")
    const onUnauth = vi.fn()
    setOnUnauth(onUnauth)
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 401 })))
    const res = await authedFetch("/api/x")
    expect(res.status).toBe(401)
    expect(onUnauth).toHaveBeenCalledTimes(1)
  })

  it("does not refresh or call onUnauth when retry=false (login/register path)", async () => {
    setAccess("old")
    const onUnauth = vi.fn()
    setOnUnauth(onUnauth)
    const f = vi.fn(async () => new Response(null, { status: 401 }))
    vi.stubGlobal("fetch", f)
    const res = await authedFetch("/api/auth/login", { method: "POST" }, false)
    expect(res.status).toBe(401)
    expect(f).toHaveBeenCalledTimes(1) // 没有去 refresh
    expect(onUnauth).not.toHaveBeenCalled()
  })
})
