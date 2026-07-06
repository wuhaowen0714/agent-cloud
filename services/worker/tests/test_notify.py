from agent_cloud_common import ToolCall, ToolResult, ToolSpec
from agent_cloud_worker.notify import NOTIFY_SPEC, NotifyingExecutor, notify_enabled


class _Inner:
    def specs(self):
        return [ToolSpec(name="bash", description="", input_schema={})]

    async def execute(self, call):
        return ToolResult(call_id=call.id, content=f"ran {call.name}", is_error=False)


def test_enabled_logic():
    assert notify_enabled([]) is True
    assert notify_enabled(["notify"]) is True
    assert notify_enabled(["bash"]) is False


def test_specs_gated():
    assert "notify" in [s.name for s in NotifyingExecutor(_Inner(), enabled=True).specs()]
    assert "notify" not in [s.name for s in NotifyingExecutor(_Inner(), enabled=False).specs()]


def test_specs_exposed_when_enabled():
    # 2026-07 起 mobile 有 WS 推送通道(backend api/push.py),notify 全平台暴露、
    # 不再按 client 门控(此前「App 无接收通道 → mobile 隐藏」的历史门控解除)。
    assert "notify" in [
        s.name for s in NotifyingExecutor(_Inner(), enabled=True).specs()
    ]


async def test_mobile_executes_notify():
    # mobile 调 notify 正常合成确认(落库 + WS 推送在 backend 侧)。
    ex = NotifyingExecutor(_Inner(), enabled=True)
    r = await ex.execute(ToolCall(id="1", name="notify", arguments={"title": "a", "body": "b"}))
    assert r.is_error is False


async def test_intercept_returns_confirmation_not_forwarded():
    ex = NotifyingExecutor(_Inner(), enabled=True)
    r = await ex.execute(
        ToolCall(id="1", name="notify", arguments={"title": "嗨", "body": "该喝药了"})
    )
    assert r.is_error is False
    assert "ran notify" not in r.content


async def test_non_notify_delegates():
    ex = NotifyingExecutor(_Inner(), enabled=True)
    r = await ex.execute(ToolCall(id="2", name="bash", arguments={"command": "ls"}))
    assert r.content == "ran bash"


async def test_validates_required_fields():
    ex = NotifyingExecutor(_Inner(), enabled=True)
    r = await ex.execute(ToolCall(id="1", name="notify", arguments={"title": "嗨"}))
    assert r.is_error


async def test_disabled_rejects():
    ex = NotifyingExecutor(_Inner(), enabled=False)
    r = await ex.execute(ToolCall(id="1", name="notify", arguments={"title": "a", "body": "b"}))
    assert r.is_error is True


def test_spec_required_fields():
    assert set(NOTIFY_SPEC.input_schema["required"]) == {"title", "body"}
