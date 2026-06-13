from agent_cloud_common import ToolCall, ToolResult, ToolSpec
from agent_cloud_worker.schedule_task import (
    SCHEDULE_TASK_SPEC,
    SchedulingExecutor,
    schedule_task_enabled,
)


class _Inner:
    def specs(self):
        return [ToolSpec(name="bash", description="", input_schema={})]

    async def execute(self, call):
        return ToolResult(call_id=call.id, content=f"ran {call.name}", is_error=False)


def test_enabled_logic():
    assert schedule_task_enabled([]) is True
    assert schedule_task_enabled(["schedule_task"]) is True
    assert schedule_task_enabled(["bash"]) is False


def test_specs_gated():
    assert "schedule_task" in [s.name for s in SchedulingExecutor(_Inner(), enabled=True).specs()]
    assert "schedule_task" not in [
        s.name for s in SchedulingExecutor(_Inner(), enabled=False).specs()
    ]
    assert "bash" in [s.name for s in SchedulingExecutor(_Inner(), enabled=True).specs()]


async def test_intercept_returns_confirmation_not_forwarded():
    ex = SchedulingExecutor(_Inner(), enabled=True)
    r = await ex.execute(
        ToolCall(
            id="1",
            name="schedule_task",
            arguments={
                "name": "晨报",
                "prompt": "总结",
                "schedule_kind": "cron",
                "schedule_expr": "0 8 * * *",
            },
        )
    )
    assert r.is_error is False
    assert "ran schedule_task" not in r.content  # 没进内层/沙箱


async def test_non_schedule_delegates():
    ex = SchedulingExecutor(_Inner(), enabled=True)
    r = await ex.execute(ToolCall(id="2", name="bash", arguments={"command": "ls"}))
    assert r.content == "ran bash"


async def test_validates_required_fields_and_kind():
    ex = SchedulingExecutor(_Inner(), enabled=True)
    miss = await ex.execute(ToolCall(id="1", name="schedule_task", arguments={"name": "x"}))
    bad_kind = await ex.execute(
        ToolCall(
            id="2",
            name="schedule_task",
            arguments={"name": "x", "prompt": "p", "schedule_kind": "weekly", "schedule_expr": "x"},
        )
    )
    assert miss.is_error
    assert bad_kind.is_error


async def test_disabled_rejects():
    ex = SchedulingExecutor(_Inner(), enabled=False)
    r = await ex.execute(
        ToolCall(
            id="1",
            name="schedule_task",
            arguments={
                "name": "x",
                "prompt": "p",
                "schedule_kind": "cron",
                "schedule_expr": "0 8 * * *",
            },
        )
    )
    assert r.is_error is True


def test_spec_required_fields():
    assert set(SCHEDULE_TASK_SPEC.input_schema["required"]) == {
        "name",
        "prompt",
        "schedule_kind",
        "schedule_expr",
    }
