from __future__ import annotations

from agent_cloud_common import ToolCall, ToolResult, ToolSpec

from agent_cloud_worker.tools import ToolExecutor

# 提醒用户工具(worker 原生:本地校验 + 合成确认,不碰 DB、不转沙箱)。tool_call/result 随
# new_messages 回 backend,落库后处理 apply_notify_calls 扫到并 INSERT notifications;前端轮询
# 拉取后弹 OS 通知 + 应用内 toast(spec 2026-06-14-notify-tool)。定时任务运行里也可调(主用例)。
NOTIFY_SPEC = ToolSpec(
    name="notify",
    description=(
        "Notify the user with an OS notification + in-app popup. Use to actively alert the user "
        "(e.g. a scheduled reminder firing, or a heads-up mid-conversation). title is a short "
        "heading; body is the message. Delivered to the user's open browser tab."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short notification heading."},
            "body": {"type": "string", "description": "Notification message body."},
        },
        "required": ["title", "body"],
    },
)


def notify_enabled(enabled_tools: list[str]) -> bool:
    """空 enabled_tools = 全部(含 notify);否则需显式列出。"""
    return not enabled_tools or "notify" in enabled_tools


class NotifyingExecutor:
    """装饰 ToolExecutor:加 worker 原生 ``notify`` 工具。本地校验 + 合成确认,**不碰 DB、不转
    沙箱**;其余委托内层。真正落库由 backend 扫 new_messages 完成(含 enabled_tools 重校验)。
    与 schedule_task 不同:**不**按 is_scheduled_run 关闭——定时任务到点提醒正是主用例。"""

    def __init__(self, inner: ToolExecutor, *, enabled: bool) -> None:
        self._inner = inner
        self._enabled = enabled

    def specs(self) -> list[ToolSpec]:
        specs = list(self._inner.specs())
        if self._enabled:
            specs.append(NOTIFY_SPEC)
        return specs

    async def execute(self, call: ToolCall) -> ToolResult:
        if call.name != "notify":
            return await self._inner.execute(call)
        if not self._enabled:
            return ToolResult(call_id=call.id, content="tool not enabled: notify", is_error=True)
        args = call.arguments or {}
        title = args.get("title")
        body = args.get("body")
        if not all(isinstance(x, str) and x.strip() for x in (title, body)):
            return ToolResult(
                call_id=call.id, content="notify: title and body are required", is_error=True
            )
        return ToolResult(call_id=call.id, content=f"Notified user: {title}", is_error=False)
