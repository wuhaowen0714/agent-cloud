import type { ToolCall, ToolResult } from "../types"

export function ToolCallCard({ call, result }: { call: ToolCall; result?: ToolResult }) {
  return (
    <div className="my-1 rounded border border-slate-200 bg-slate-50 p-2 text-xs">
      <div className="font-mono text-slate-700">
        🔧 {call.name}({JSON.stringify(call.arguments)})
      </div>
      {result && (
        <pre
          className={`mt-1 max-h-60 overflow-auto whitespace-pre-wrap font-mono ${
            result.is_error ? "text-red-600" : "text-slate-500"
          }`}
        >
          {result.is_error ? "[error] " : "→ "}
          {result.content}
        </pre>
      )}
    </div>
  )
}
