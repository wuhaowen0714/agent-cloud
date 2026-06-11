import { describe, expect, it } from "vitest"
import { isNearBottom } from "./scroll"

const el = (scrollHeight: number, scrollTop: number, clientHeight: number) => ({
  scrollHeight, scrollTop, clientHeight,
})

describe("isNearBottom", () => {
  it("距底小于阈值 → true(含恰在底部)", () => {
    expect(isNearBottom(el(1000, 960, 40))).toBe(true) // 距底 0
    expect(isNearBottom(el(1000, 921, 40))).toBe(true) // 距底 39
  })

  it("距底达到/超过阈值 → false", () => {
    expect(isNearBottom(el(1000, 920, 40))).toBe(false) // 距底 40
    expect(isNearBottom(el(1000, 100, 40))).toBe(false)
  })

  it("自定义阈值", () => {
    expect(isNearBottom(el(1000, 800, 40), 200)).toBe(true) // 距底 160 < 200
  })
})
