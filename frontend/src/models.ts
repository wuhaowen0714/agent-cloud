// 模型选择按 provider 维度组织(session 级):平台 sophnet + 各 BYOK provider。
// 模型候选 = 平台清单(后端 /platform/models)∪ 每个 credential 自己的 models。

export const PLATFORM_PROVIDER = "sophnet" // 平台默认 provider(对应后端全局 key)
export const DEFAULT_MODEL = "DeepSeek-V4-Pro" // 平台 config 不可达时的前端兜底

export interface ProviderOption {
  name: string // 展示名:平台为 "sophnet",BYOK 为 credential.name
  credentialId: string | null // null = 平台 sophnet 全局 key
  models: string[] // 该 provider 下可选模型
  visionModels: string[] // models 中支持图片输入的子集(spec: image-understanding)
}

// 平台 + 各 BYOK credential → 图一第一栏的 provider 选项。BYOK 凭据未标 vision 的视为不支持图片。
export function buildProviderOptions(
  platformModels: string[],
  platformVisionModels: string[],
  credentials: { id: string; name: string; models: string[]; visionModels?: string[] }[],
): ProviderOption[] {
  return [
    {
      name: PLATFORM_PROVIDER,
      credentialId: null,
      models: platformModels,
      visionModels: platformVisionModels,
    },
    ...credentials.map((c) => ({
      name: c.name,
      credentialId: c.id,
      models: c.models,
      visionModels: c.visionModels ?? [],
    })),
  ]
}

// 当前 provider 下某 model 是否支持图片输入(Composer 路由判断用)。
export function isVisionModel(provider: ProviderOption, model: string): boolean {
  return provider.visionModels.includes(model)
}

// 给定 session 的 (model, credential_id),在 provider 选项里定位它属于哪个 provider。
// 找不到(凭据被删/模型已不在清单)→ 回退平台,让 UI 仍能渲染当前 model。
export function findProvider(
  providers: ProviderOption[],
  credentialId: string | null,
): ProviderOption {
  return (
    providers.find((p) => p.credentialId === credentialId) ??
    providers[0] ?? { name: PLATFORM_PROVIDER, credentialId: null, models: [], visionModels: [] }
  )
}
