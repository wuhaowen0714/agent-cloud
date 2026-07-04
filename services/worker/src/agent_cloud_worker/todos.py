from __future__ import annotations

from agent_cloud_common import ToolCall, ToolResult, ToolSpec

from agent_cloud_worker.tools import ToolExecutor

# 任务清单工具(worker 原生:本地校验 + 合成确认,不碰 DB、不进沙箱)。清单本体就存在
# tool_call 的 arguments 里,随消息自然落库——前端从(最新一次)todo 调用的 args 渲染
# 置顶进度卡/历史清单卡,后端零改动。全量替换语义(对标 Claude Code 的 TodoWrite):
# 增量 create/update 需要服务端状态与 id 管理,全量写幂等、模型也更不易写错。
TODO_SPEC = ToolSpec(
    name="todo",
    description=(
        "Maintain the task checklist for the CURRENT job (plan mode). For any multi-step task: "
        "FIRST call this with the full plan (all items pending) so the user sees what you are "
        "about to do; then update it as you work — set an item to in_progress before starting "
        "it and to completed right after finishing it (call again with the FULL updated list; "
        "items fully replace the previous list). Exactly one item should be in_progress at a "
        "time. Keep item text short (a few words). Skip this tool for trivial single-step "
        "requests or pure conversation."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "The FULL checklist, replacing the previous one (ordered).",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Short description of the step.",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                        },
                    },
                    "required": ["content", "status"],
                },
            },
        },
        "required": ["items"],
    },
)

_STATUSES = ("pending", "in_progress", "completed")


def todo_enabled(enabled_tools: list[str]) -> bool:
    """空 enabled_tools = 全部(含 todo),与其它工具一致;否则需显式列出。"""
    return not enabled_tools or "todo" in enabled_tools


class TodoExecutor:
    """装饰 ToolExecutor:加 worker 原生的 ``todo`` 任务清单工具。

    本地校验 + 合成确认;清单不在 worker 存状态(全量替换,真相在消息流里),
    其余工具委托内层。
    """

    def __init__(self, inner: ToolExecutor, *, enabled: bool) -> None:
        self._inner = inner
        self._enabled = enabled

    def specs(self) -> list[ToolSpec]:
        specs = list(self._inner.specs())
        if self._enabled:
            specs.append(TODO_SPEC)
        return specs

    async def execute(self, call: ToolCall) -> ToolResult:
        if call.name != "todo":
            return await self._inner.execute(call)
        if not self._enabled:
            return ToolResult(call_id=call.id, content="tool not enabled: todo", is_error=True)
        items = (call.arguments or {}).get("items")
        if not isinstance(items, list) or not items:
            return ToolResult(
                call_id=call.id,
                content="todo: 'items' (non-empty array of {content,status}) is required",
                is_error=True,
            )
        done = doing = 0
        doing_text = ""
        for it in items:
            if not isinstance(it, dict):
                return ToolResult(
                    call_id=call.id, content="todo: each item must be an object", is_error=True
                )
            content = it.get("content")
            status = it.get("status")
            if not isinstance(content, str) or not content.strip():
                return ToolResult(
                    call_id=call.id,
                    content="todo: item 'content' (non-empty string) is required",
                    is_error=True,
                )
            if status not in _STATUSES:
                return ToolResult(
                    call_id=call.id,
                    content="todo: item 'status' must be pending|in_progress|completed",
                    is_error=True,
                )
            if status == "completed":
                done += 1
            elif status == "in_progress":
                doing += 1
                if not doing_text:
                    doing_text = content.strip()
        suffix = f",进行中:{doing_text}" if doing_text else ""
        return ToolResult(
            call_id=call.id,
            content=f"任务清单已更新:{done}/{len(items)} 完成{suffix}。",
            is_error=False,
        )
