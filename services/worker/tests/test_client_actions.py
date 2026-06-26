"""客户端动作工具(set_alarm / add_calendar_event)测试。"""

from agent_cloud_common import ToolCall, ToolResult
from agent_cloud_worker.client_actions import (
    ClientActionsExecutor,
    add_calendar_enabled,
    set_alarm_enabled,
)


class _Inner:
    def specs(self):
        return []

    async def execute(self, call):
        return ToolResult(call_id=call.id, content="inner", is_error=False)


def test_enabled_helpers():
    assert set_alarm_enabled([])  # 空 = 全部
    assert set_alarm_enabled(["set_alarm"])
    assert not set_alarm_enabled(["bash"])
    assert add_calendar_enabled([])
    assert not add_calendar_enabled(["bash"])


def test_specs_gated_by_enabled():
    names = {s.name for s in ClientActionsExecutor(_Inner(), enabled_tools=[]).specs()}
    assert {"set_alarm", "add_calendar_event"} <= names
    names2 = {s.name for s in ClientActionsExecutor(_Inner(), enabled_tools=["bash"]).specs()}
    assert "set_alarm" not in names2 and "add_calendar_event" not in names2


async def test_set_alarm_ok():
    ex = ClientActionsExecutor(_Inner(), enabled_tools=[])
    r = await ex.execute(
        ToolCall(id="1", name="set_alarm", arguments={"hour": 7, "minute": 30, "label": "起床"})
    )
    assert not r.is_error
    assert "07:30" in r.content and "起床" in r.content


async def test_set_alarm_bad_time():
    ex = ClientActionsExecutor(_Inner(), enabled_tools=[])
    r = await ex.execute(ToolCall(id="1", name="set_alarm", arguments={"hour": 25, "minute": 0}))
    assert r.is_error


async def test_add_calendar_ok():
    ex = ClientActionsExecutor(_Inner(), enabled_tools=[])
    r = await ex.execute(
        ToolCall(
            id="1",
            name="add_calendar_event",
            arguments={"title": "开会", "start": "2026-06-27T09:00"},
        )
    )
    assert not r.is_error
    assert "开会" in r.content


async def test_add_calendar_missing_title():
    ex = ClientActionsExecutor(_Inner(), enabled_tools=[])
    r = await ex.execute(
        ToolCall(id="1", name="add_calendar_event", arguments={"start": "2026-06-27T09:00"})
    )
    assert r.is_error


async def test_passthrough_other_tools():
    ex = ClientActionsExecutor(_Inner(), enabled_tools=[])
    r = await ex.execute(ToolCall(id="1", name="bash", arguments={"command": "ls"}))
    assert r.content == "inner"
