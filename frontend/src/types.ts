export interface User { id: string; email: string }
export interface AgentConfig {
  // 模型/provider/凭据已下放到 session 级;agent 只剩工具/人设/记忆。
  id: string; user_id: string; name: string
  enabled_tools: string[]; permissions: Record<string, unknown>
}
export interface ProviderCredential { id: string; name: string; base_url: string; masked: string; models: string[]; created_at: string }
export interface MemoryBlock { scope: string; owner_id: string; content: string; version: number }
export interface PlatformModels { models: string[]; default: string }
export interface Session { id: string; user_id: string; agent_config_id: string; model: string; credential_id: string | null; title: string | null; work_subdir: string; last_active_at: string; last_context_tokens: number | null; scheduled_task_id: string | null; unread: boolean }
export interface ScheduledTask {
  id: string; user_id: string; agent_config_id: string; name: string; prompt: string
  schedule_kind: "once" | "interval" | "cron"; schedule_expr: string; schedule_tz: string
  enabled: boolean; next_run_at: string | null; last_run_at: string | null
  last_status: "ok" | "error" | "skipped" | null; last_error: string | null
  last_delivery_error: string | null; last_run_session_id: string | null; created_at: string
}

export interface ToolCall { id: string; name: string; arguments: Record<string, unknown> }
export interface ToolResult { call_id: string; content: string; is_error: boolean }
export interface MessageContent { text: string; tool_calls: ToolCall[]; tool_results: ToolResult[] }
export interface Message { id: string; seq: number; role: "user" | "assistant" | "tool"; content: MessageContent; created_at: string }

// SSE 回合事件(后端 turn_event_to_sse 的形状)
export type TurnEvent =
  | { type: "text_delta"; text: string }
  | { type: "thinking_delta"; text: string }
  | { type: "tool_call_start"; call_id: string; tool: string; args: Record<string, unknown> }
  | { type: "tool_call_progress"; call_id: string; tool: string; args_chars: number; lines: number; path: string }
  | { type: "tool_result"; call_id: string; result: string; is_error: boolean }
  | { type: "turn_done"; usage: { input_tokens: number; output_tokens: number }; message_ids: string[]; stop_reason: string }
  | { type: "error"; message: string; recoverable: boolean }
  | { type: "reset" }  // 透明自动重试:清掉本回合已显示内容,从头重来

// 手动压缩结果四态:压缩了 / 没东西可压 / 会话忙(回合进行中)/ 出错。
// 定义在此(而非 slash/commands)以便 store 引用而不形成 store↔commands 循环依赖。
export type CompactResult = "compacted" | "nothing" | "busy" | "error"

export interface FileEntry { name: string; path: string; is_dir: boolean; size: number; mtime: number }
export interface Skill { id: string; user_id: string; name: string; description: string; source: string; version: string }
export interface ContextDocument { id: string; scope: string; type: string; owner_id: string; content: string }
export interface Notification {
  id: string
  title: string
  body: string
  origin_session_id: string | null
  created_at: string
}
