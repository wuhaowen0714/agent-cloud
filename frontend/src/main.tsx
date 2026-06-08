import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import App from "./App"
import { setQueryClient } from "./api/queryClient"
import "./index.css"

// refetchOnWindowFocus 关闭:聊天历史不应因切换标签页/窗口失焦再聚焦而在回合进行中重新拉取
// ——那会和「乐观渲染的用户消息」(live.userText)重复出现。历史只在 turn_done 后主动失效刷新。
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
})
setQueryClient(queryClient) // 让 store.logout() 能清空缓存(见 api/queryClient.ts)

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
