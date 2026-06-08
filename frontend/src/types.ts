export interface User { id: string; email: string }
export interface AgentConfig {
  id: string; user_id: string; name: string; model: string; provider: string
  thinking_level: string | null; enabled_tools: string[]; permissions: Record<string, unknown>
}
export interface Session { id: string; user_id: string; agent_config_id: string; title: string | null; work_subdir: string }

export interface ToolCall { id: string; name: string; arguments: Record<string, unknown> }
export interface ToolResult { call_id: string; content: string; is_error: boolean }
export interface MessageContent { text: string; tool_calls: ToolCall[]; tool_results: ToolResult[] }
export interface Message { id: string; seq: number; role: "user" | "assistant" | "tool"; content: MessageContent }

// SSE 回合事件(后端 turn_event_to_sse 的形状)
export type TurnEvent =
  | { type: "text_delta"; text: string }
  | { type: "thinking_delta"; text: string }
  | { type: "tool_call_start"; call_id: string; tool: string; args: Record<string, unknown> }
  | { type: "tool_result"; call_id: string; result: string; is_error: boolean }
  | { type: "turn_done"; usage: { input_tokens: number; output_tokens: number }; message_ids: string[]; stop_reason: string }
  | { type: "error"; message: string; recoverable: boolean }
  | { type: "reset" }  // 透明自动重试:清掉本回合已显示内容,从头重来

export interface FileEntry { name: string; path: string; is_dir: boolean; size: number; mtime: number }
export interface Skill { id: string; user_id: string; name: string; description: string; source: string; version: string }
export interface ContextDocument { id: string; scope: string; type: string; owner_id: string; content: string }
