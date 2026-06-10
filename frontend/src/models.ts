import type { UserModel } from "./types"

// 模型选单的预设;DEFAULT_MODEL 是「创建 agent 免填模型」时的预设值。
export const PRESET_MODELS = ["DeepSeek-V4-Pro", "DeepSeek-V4-Flash", "GLM-5.1"]
export const DEFAULT_MODEL = "DeepSeek-V4-Pro"

export interface ModelOption {
  model: string
  custom?: UserModel // 仅用户自定义条目携带(供删除);预设/在用没有
}

// 合并去重:预设 → 在用 → 自定义;trim、去空、保序。
export function mergeModelOptions(inUse: string[], customs: UserModel[]): ModelOption[] {
  const seen = new Set<string>()
  const out: ModelOption[] = []
  for (const m of PRESET_MODELS) {
    seen.add(m)
    out.push({ model: m })
  }
  for (const raw of inUse) {
    const m = raw?.trim()
    if (m && !seen.has(m)) {
      seen.add(m)
      out.push({ model: m })
    }
  }
  for (const c of customs) {
    const m = c.model.trim()
    if (m && !seen.has(m)) {
      seen.add(m)
      out.push({ model: m, custom: c })
    }
  }
  return out
}
