import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "../../api/client"
import { mergeModelOptions, type ModelOption } from "../../models"
import { useStore } from "../../store"

// 模型选单的选项源:预设 ∪ 各 agent 在用 ∪ 用户自定义(后端持久化)。
// agents/userModels 都走订阅式 useQuery(与 AgentRail 等共享缓存),变更即重渲染。
export function useModelOptions(): {
  options: ModelOption[]
  addModel: (model: string) => Promise<string>
  removeModel: (id: string) => Promise<void>
} {
  const userId = useStore((s) => s.userId)
  const qc = useQueryClient()
  const { data: customs = [] } = useQuery({
    queryKey: ["userModels", userId],
    queryFn: () => api.listModels(),
    enabled: !!userId,
  })
  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })
  const invalidate = () => qc.invalidateQueries({ queryKey: ["userModels", userId] })
  const add = useMutation({ mutationFn: (m: string) => api.addModel(m), onSuccess: invalidate })
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteModel(id),
    onSuccess: invalidate,
  })
  return {
    options: mergeModelOptions(
      agents.map((a) => a.model),
      customs,
    ),
    addModel: async (m) => (await add.mutateAsync(m.trim())).model,
    removeModel: async (id) => {
      await remove.mutateAsync(id)
    },
  }
}
