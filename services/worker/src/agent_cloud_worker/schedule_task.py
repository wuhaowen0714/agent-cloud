from __future__ import annotations

from agent_cloud_common import ToolCall, ToolResult, ToolSpec

from agent_cloud_worker.tools import ToolExecutor

# agent 主动排期工具(worker 原生:本地校验 + 合成确认,绝不进沙箱、不碰 DB)。tool_call/result
# 随 new_messages 流回,backend 在落库后扫到它、做权威校验并 INSERT scheduled_tasks
# (spec 2026-06-13-scheduled-tasks)。
SCHEDULE_TASK_SPEC = ToolSpec(
    name="schedule_task",
    description=(
        "Schedule a recurring or one-off task: at the scheduled time, a fresh session is "
        "created and you are re-run with the given prompt, producing a report the user can read "
        "later. Use for 'every morning summarize X', 'remind me at 3pm', 'check Y hourly'. "
        "schedule_kind: 'once' (schedule_expr = ISO8601 datetime), 'interval' (schedule_expr = "
        "seconds or like '30m'/'2h'/'1d', min 60s), or 'cron' (schedule_expr = 5-field cron, "
        "schedule_tz like 'Asia/Shanghai'). The prompt should be self-contained — the scheduled "
        "run has no memory of this conversation."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short human label for the task."},
            "prompt": {
                "type": "string",
                "description": "Self-contained instruction to run each time.",
            },
            "schedule_kind": {"type": "string", "enum": ["once", "interval", "cron"]},
            "schedule_expr": {
                "type": "string",
                "description": "once: ISO8601; interval: seconds or 30m/2h/1d; cron: 5-field expr.",
            },
            "schedule_tz": {
                "type": "string",
                "description": "IANA tz for cron (default Asia/Shanghai).",
            },
        },
        "required": ["name", "prompt", "schedule_kind", "schedule_expr"],
    },
)

_KINDS = ("once", "interval", "cron")


def schedule_task_enabled(enabled_tools: list[str]) -> bool:
    """空 enabled_tools = 全部(含 schedule_task);否则需显式列出。"""
    return not enabled_tools or "schedule_task" in enabled_tools


class SchedulingExecutor:
    """装饰 ToolExecutor:加 worker 原生的 ``schedule_task`` 工具。本地校验 + 返回合成确认,
    **绝不转发沙箱、不碰 DB**;其余工具委托内层。真正落库由 backend 扫 new_messages 完成
    (含 enabled_tools 重校验 + 排期合法性 + 自排期护栏)。"""

    def __init__(self, inner: ToolExecutor, *, enabled: bool) -> None:
        self._inner = inner
        self._enabled = enabled

    def specs(self) -> list[ToolSpec]:
        specs = list(self._inner.specs())
        if self._enabled:
            specs.append(SCHEDULE_TASK_SPEC)
        return specs

    async def execute(self, call: ToolCall) -> ToolResult:
        if call.name != "schedule_task":
            return await self._inner.execute(call)
        if not self._enabled:
            return ToolResult(
                call_id=call.id, content="tool not enabled: schedule_task", is_error=True
            )
        args = call.arguments or {}
        name = args.get("name")
        prompt = args.get("prompt")
        kind = args.get("schedule_kind")
        expr = args.get("schedule_expr")
        if not all(isinstance(x, str) and x.strip() for x in (name, prompt, kind, expr)):
            return ToolResult(
                call_id=call.id,
                content="schedule_task: name/prompt/schedule_kind/schedule_expr are all required",
                is_error=True,
            )
        if kind not in _KINDS:
            return ToolResult(
                call_id=call.id,
                content="schedule_task: schedule_kind must be once/interval/cron",
                is_error=True,
            )
        # 合成确认;真正校验(croniter/时区/最小间隔)与落库由 backend 完成。
        return ToolResult(call_id=call.id, content=f"Scheduled '{name}' ({kind}).", is_error=False)
