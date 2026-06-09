from __future__ import annotations

from agent_cloud_common import ToolCall, ToolResult, ToolSpec

from agent_cloud_worker.tools import ToolExecutor

# agent 主动记忆工具(worker 原生:本地处理、绝不进沙箱)。tool_call/result 随 new_messages
# 流回,backend 在 _persist 里把它落库到记忆块(spec 2026-06-09-remember-tool)。
REMEMBER_SPEC = ToolSpec(
    name="remember",
    description=(
        "Save a durable, cross-session fact to long-term memory. Use for stable facts worth "
        "recalling in future conversations: the user's identity / role / lasting preferences "
        "(scope='user', shared across all of their agents), or facts specific to THIS agent's "
        "work or project (scope='agent'). Do NOT use for transient or one-off details. "
        "Keep each entry short."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The fact to remember (concise)."},
            "scope": {
                "type": "string",
                "enum": ["user", "agent"],
                "description": "'user' = about the person; 'agent' = this agent's work.",
            },
        },
        "required": ["content"],
    },
)


def remember_enabled(enabled_tools: list[str]) -> bool:
    """空 enabled_tools = 全部(含 remember),与其它工具一致;否则需显式列出。"""
    return not enabled_tools or "remember" in enabled_tools


class RememberingExecutor:
    """装饰 ToolExecutor:把 worker 原生的 ``remember`` 工具加进来。

    ``remember`` 在 worker 本地处理(校验 + 返回合成确认),**绝不转发沙箱**;其余工具
    委托给内层 executor。真正落库由 backend 扫 new_messages 完成,这里不碰 DB。
    """

    def __init__(self, inner: ToolExecutor, *, enabled: bool) -> None:
        self._inner = inner
        self._enabled = enabled

    def specs(self) -> list[ToolSpec]:
        specs = list(self._inner.specs())
        if self._enabled:
            specs.append(REMEMBER_SPEC)
        return specs

    async def execute(self, call: ToolCall) -> ToolResult:
        if call.name != "remember":
            return await self._inner.execute(call)
        if not self._enabled:
            return ToolResult(call_id=call.id, content="tool not enabled: remember", is_error=True)
        args = call.arguments or {}
        content = args.get("content")
        scope = args.get("scope", "user")
        if not isinstance(content, str) or not content.strip():
            return ToolResult(
                call_id=call.id,
                content="remember: 'content' (non-empty string) is required",
                is_error=True,
            )
        if scope not in ("user", "agent"):
            return ToolResult(
                call_id=call.id,
                content="remember: 'scope' must be 'user' or 'agent'",
                is_error=True,
            )
        # 仅返回合成确认;真正写入记忆块由 backend 在 _persist 扫到本次 remember 调用后完成。
        return ToolResult(call_id=call.id, content=f"Remembered ({scope}).", is_error=False)
