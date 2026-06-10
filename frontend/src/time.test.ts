import { describe, expect, it } from "vitest"
import { fmtTime } from "./time"

// 无时区后缀的 ISO 按本地时区解析,与 fmtTime 的本地输出一致 → 断言跨机器稳定
describe("fmtTime", () => {
  const now = new Date("2026-06-10T20:00:00")

  it("今天:只显示时分(补零)", () => {
    expect(fmtTime("2026-06-10T14:32:00", now)).toBe("14:32")
    expect(fmtTime("2026-06-10T09:05:00", now)).toBe("09:05")
  })

  it("今年非今天:月-日 时:分", () => {
    expect(fmtTime("2026-03-05T09:07:00", now)).toBe("03-05 09:07")
  })

  it("跨年:全量日期", () => {
    expect(fmtTime("2025-12-31T23:59:00", now)).toBe("2025-12-31 23:59")
  })

  it("后端真实形态(Z 后缀 + 微秒):按本地时区显示(vitest 钉 TZ=Asia/Shanghai)", () => {
    // UTC 12:34 → 上海 20:34;若实现退化成字符串切片(不转本地),此处立即红
    expect(fmtTime("2026-06-10T12:34:56.789012Z", now)).toBe("20:34")
  })

  it("坏值不上屏 NaN:返回空串", () => {
    expect(fmtTime("not-a-date", now)).toBe("")
    expect(fmtTime("", now)).toBe("")
  })
})
