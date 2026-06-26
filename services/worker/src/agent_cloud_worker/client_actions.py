from __future__ import annotations

from agent_cloud_common import ToolCall, ToolResult, ToolSpec

from agent_cloud_worker.tools import ToolExecutor

# 客户端动作工具(worker 原生:本地校验 + 合成确认,不碰 DB、不转沙箱)。真正的副作用在用户
# **设备**上由 App 执行 —— App 收到这些 tool_call(随回合流下发)后调系统 Intent 设手机闹钟 /
# 加系统日历。tool_call/result 随 new_messages 回 backend 落库,App 据此执行(同 notify 把副作用
# 留给客户端的思路)。LLM 拿到合成确认即可继续对话(fire-and-forget,不阻塞回合等设备回传)。
SET_ALARM_SPEC = ToolSpec(
    name="set_alarm",
    description=(
        "Set an alarm on the user's phone. Use when the user asks to set/create an alarm or a "
        "reminder at a specific clock time. hour/minute use a 24-hour clock. label is an optional "
        "name shown on the alarm. The alarm is set on the user's own device."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "hour": {"type": "integer", "description": "Hour, 0-23."},
            "minute": {"type": "integer", "description": "Minute, 0-59."},
            "label": {"type": "string", "description": "Optional alarm label."},
        },
        "required": ["hour", "minute"],
    },
)

ADD_CALENDAR_SPEC = ToolSpec(
    name="add_calendar_event",
    description=(
        "Add an event to the user's phone calendar. Use when the user asks to schedule or create a "
        "calendar event/appointment. start (and optional end) are ISO 8601 local datetime like "
        "2026-06-27T09:00. The event is added on the user's own device calendar."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Event title."},
            "start": {"type": "string", "description": "ISO 8601 start, e.g. 2026-06-27T09:00."},
            "end": {"type": "string", "description": "ISO 8601 end (optional)."},
            "location": {"type": "string", "description": "Optional location."},
            "description": {"type": "string", "description": "Optional details."},
        },
        "required": ["title", "start"],
    },
)

NAVIGATE_SPEC = ToolSpec(
    name="start_navigation",
    description=(
        "Start map navigation to a destination on the user's phone (opens the Amap/Baidu map app). "
        "Use when the user asks to navigate / drive / go to a place. destination is a place name or "
        "address in Chinese or English — the map app searches it itself, NO coordinates needed. mode "
        "is the travel mode, default driving. Navigation starts on the user's own device."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "destination": {
                "type": "string",
                "description": "Destination place name or address, e.g. 北京南站 / 人民广场 / Shanghai Tower.",
            },
            "mode": {
                "type": "string",
                "enum": ["driving", "walking", "transit", "riding"],
                "description": "Travel mode; default driving.",
            },
        },
        "required": ["destination"],
    },
)


def set_alarm_enabled(enabled_tools: list[str]) -> bool:
    """空 enabled_tools = 全部(含 set_alarm);否则需显式列出。"""
    return not enabled_tools or "set_alarm" in enabled_tools


def add_calendar_enabled(enabled_tools: list[str]) -> bool:
    return not enabled_tools or "add_calendar_event" in enabled_tools


def start_navigation_enabled(enabled_tools: list[str]) -> bool:
    return not enabled_tools or "start_navigation" in enabled_tools


class ClientActionsExecutor:
    """装饰 ToolExecutor:加客户端动作工具 set_alarm / add_calendar_event。worker 本地校验 +
    合成确认,**不碰 DB、不转沙箱**;真正的副作用在用户设备上由 App 执行(收到 tool_call 后调
    系统 Intent)。其余工具委托内层。

    按 client 平台门控:这两个工具只有 mobile App 能落到系统闹钟/日历,故仅 client=="mobile"
    时暴露;web/未知端不暴露(暴露只会诱导 LLM 调一个落不了地的工具)。再叠加 enabled_tools。"""

    def __init__(
        self, inner: ToolExecutor, *, enabled_tools: list[str], client: str = ""
    ) -> None:
        self._inner = inner
        # 仅 mobile 暴露:web 没有系统闹钟/日历的执行通道;空 client(未知/旧客户端)按非 mobile
        # 保守处理。仍叠加 enabled_tools 门控(per-agent 工具开关)。
        is_mobile = client == "mobile"
        self._alarm = is_mobile and set_alarm_enabled(enabled_tools)
        self._cal = is_mobile and add_calendar_enabled(enabled_tools)
        self._nav = is_mobile and start_navigation_enabled(enabled_tools)

    def specs(self) -> list[ToolSpec]:
        specs = list(self._inner.specs())
        if self._alarm:
            specs.append(SET_ALARM_SPEC)
        if self._cal:
            specs.append(ADD_CALENDAR_SPEC)
        if self._nav:
            specs.append(NAVIGATE_SPEC)
        return specs

    async def execute(self, call: ToolCall) -> ToolResult:
        if call.name == "set_alarm":
            if not self._alarm:
                return ToolResult(
                    call_id=call.id, content="tool not enabled: set_alarm", is_error=True
                )
            return self._set_alarm(call)
        if call.name == "add_calendar_event":
            if not self._cal:
                return ToolResult(
                    call_id=call.id, content="tool not enabled: add_calendar_event", is_error=True
                )
            return self._add_calendar(call)
        if call.name == "start_navigation":
            if not self._nav:
                return ToolResult(
                    call_id=call.id, content="tool not enabled: start_navigation", is_error=True
                )
            return self._navigate(call)
        return await self._inner.execute(call)

    def _set_alarm(self, call: ToolCall) -> ToolResult:
        args = call.arguments or {}
        hour, minute = args.get("hour"), args.get("minute")
        ok = (
            isinstance(hour, int)
            and 0 <= hour <= 23
            and isinstance(minute, int)
            and 0 <= minute <= 59
        )
        if not ok:
            return ToolResult(
                call_id=call.id,
                content="set_alarm: integer hour 0-23 and minute 0-59 required",
                is_error=True,
            )
        label = args.get("label")
        label_str = f" 「{label}」" if isinstance(label, str) and label.strip() else ""
        return ToolResult(
            call_id=call.id,
            content=f"已在用户设备上发起闹钟设置:{hour:02d}:{minute:02d}{label_str}。",
            is_error=False,
        )

    def _add_calendar(self, call: ToolCall) -> ToolResult:
        args = call.arguments or {}
        title, start = args.get("title"), args.get("start")
        ok = (
            isinstance(title, str)
            and title.strip()
            and isinstance(start, str)
            and start.strip()
        )
        if not ok:
            return ToolResult(
                call_id=call.id,
                content="add_calendar_event: title and start (ISO 8601) required",
                is_error=True,
            )
        return ToolResult(
            call_id=call.id,
            content=f"已在用户设备日历上发起事件创建:「{title}」({start})。",
            is_error=False,
        )

    def _navigate(self, call: ToolCall) -> ToolResult:
        args = call.arguments or {}
        dest = args.get("destination")
        if not (isinstance(dest, str) and dest.strip()):
            return ToolResult(
                call_id=call.id,
                content="start_navigation: destination (place name or address) required",
                is_error=True,
            )
        mode = args.get("mode")
        mode_cn = {
            "driving": "驾车",
            "walking": "步行",
            "transit": "公交",
            "riding": "骑行",
        }.get(mode if isinstance(mode, str) else "", "")
        suffix = f"({mode_cn})" if mode_cn else ""
        return ToolResult(
            call_id=call.id,
            content=f"已在用户设备上发起导航{suffix}:前往「{dest.strip()}」。",
            is_error=False,
        )
