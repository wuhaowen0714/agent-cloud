import { describe, expect, it } from "vitest"

import { buildProviderOptions, DEFAULT_MODEL, findProvider, PLATFORM_PROVIDER } from "./models"

describe("models", () => {
  it("默认模型 + 平台 provider 常量", () => {
    expect(DEFAULT_MODEL).toBe("DeepSeek-V4-Pro")
    expect(PLATFORM_PROVIDER).toBe("sophnet")
  })

  it("buildProviderOptions:平台 sophnet 在首,各 credential 跟随", () => {
    const ps = buildProviderOptions(
      ["DeepSeek-V4-Pro", "GLM-5.1"],
      [{ id: "c1", name: "openrouter", models: ["gpt-4o", "claude"] }],
    )
    expect(ps).toEqual([
      { name: "sophnet", credentialId: null, models: ["DeepSeek-V4-Pro", "GLM-5.1"] },
      { name: "openrouter", credentialId: "c1", models: ["gpt-4o", "claude"] },
    ])
  })

  it("findProvider:按 credentialId 定位;null=平台;找不到(凭据被删)回退首个", () => {
    const ps = buildProviderOptions(["m1"], [{ id: "c1", name: "or", models: ["x"] }])
    expect(findProvider(ps, null).name).toBe("sophnet")
    expect(findProvider(ps, "c1").name).toBe("or")
    expect(findProvider(ps, "gone").name).toBe("sophnet")
  })
})
