import { describe, expect, it } from "vitest"

import {
  buildProviderOptions,
  DEFAULT_MODEL,
  findProvider,
  isVisionModel,
  PLATFORM_PROVIDER,
} from "./models"

describe("models", () => {
  it("默认模型 + 平台 provider 常量", () => {
    expect(DEFAULT_MODEL).toBe("DeepSeek-V4-Pro")
    expect(PLATFORM_PROVIDER).toBe("sophnet")
  })

  it("buildProviderOptions:平台 sophnet 在首,各 credential 跟随,带 visionModels", () => {
    const ps = buildProviderOptions(
      ["DeepSeek-V4-Pro", "Kimi-K2.6"],
      ["Kimi-K2.6"],
      [{ id: "c1", name: "openrouter", models: ["gpt-4o", "claude"], visionModels: ["gpt-4o"] }],
    )
    expect(ps).toEqual([
      {
        name: "sophnet",
        credentialId: null,
        models: ["DeepSeek-V4-Pro", "Kimi-K2.6"],
        visionModels: ["Kimi-K2.6"],
      },
      {
        name: "openrouter",
        credentialId: "c1",
        models: ["gpt-4o", "claude"],
        visionModels: ["gpt-4o"],
      },
    ])
  })

  it("buildProviderOptions:BYOK 未标 visionModels → 空数组", () => {
    const ps = buildProviderOptions(["m"], [], [{ id: "c1", name: "or", models: ["x"] }])
    expect(ps[1].visionModels).toEqual([])
  })

  it("isVisionModel:按 provider 的 visionModels 判断", () => {
    const ps = buildProviderOptions(["DeepSeek-V4-Pro", "Kimi-K2.6"], ["Kimi-K2.6"], [])
    expect(isVisionModel(ps[0], "Kimi-K2.6")).toBe(true)
    expect(isVisionModel(ps[0], "DeepSeek-V4-Pro")).toBe(false)
  })

  it("findProvider:按 credentialId 定位;null=平台;找不到(凭据被删)回退首个", () => {
    const ps = buildProviderOptions(["m1"], [], [{ id: "c1", name: "or", models: ["x"] }])
    expect(findProvider(ps, null).name).toBe("sophnet")
    expect(findProvider(ps, "c1").name).toBe("or")
    expect(findProvider(ps, "gone").name).toBe("sophnet")
  })
})
