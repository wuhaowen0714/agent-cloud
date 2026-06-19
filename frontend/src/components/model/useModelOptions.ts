import { useQuery } from "@tanstack/react-query"

import { api } from "../../api/client"
import { buildProviderOptions, DEFAULT_MODEL, type ProviderOption } from "../../models"
import { useStore } from "../../store"

// 图一模型选单的数据源:平台模型清单(后端 /platform/models config)+ 各 BYOK credential
// 的 models,组织成 provider 维度。credentials 缓存变更(图三增删)即重渲染。
export function useProviderOptions(): { providers: ProviderOption[] } {
  const userId = useStore((s) => s.userId)
  const { data: platform } = useQuery({
    queryKey: ["platformModels"],
    queryFn: () => api.getPlatformModels(),
    enabled: !!userId,
  })
  const { data: creds = [] } = useQuery({
    queryKey: ["credentials", userId],
    queryFn: () => api.listCredentials(),
    enabled: !!userId,
  })
  return {
    providers: buildProviderOptions(
      platform?.models ?? [DEFAULT_MODEL],
      platform?.vision_models ?? [],
      creds,
    ),
  }
}
