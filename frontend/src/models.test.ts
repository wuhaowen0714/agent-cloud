import { describe, expect, it } from "vitest"
import { DEFAULT_MODEL, mergeModelOptions, PRESET_MODELS } from "./models"

describe("models", () => {
  it("预设含默认模型", () => {
    expect(PRESET_MODELS).toContain(DEFAULT_MODEL)
    expect(DEFAULT_MODEL).toBe("DeepSeek-V4-Pro")
  })

  it("合并顺序:预设 → 在用 → 自定义;trim 去空去重;自定义携带行", () => {
    const customs = [
      { id: "c1", model: "GLM-5.1", created_at: "" }, // 与预设重复 → 不再出现
      { id: "c2", model: "my-model", created_at: "" },
    ]
    const opts = mergeModelOptions(["gpt-x", " DeepSeek-V4-Pro ", ""], customs)
    expect(opts.map((o) => o.model)).toEqual([...PRESET_MODELS, "gpt-x", "my-model"])
    expect(opts.find((o) => o.model === "my-model")?.custom?.id).toBe("c2")
    expect(opts.find((o) => o.model === "GLM-5.1")?.custom).toBeUndefined()
  })
})
