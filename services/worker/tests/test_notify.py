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


def test_specs_gated_by_client():
    # mobile 无 notifications 接收通道 → 不暴露 notify(与 client_actions 的 mobile-only 相反)。
    assert "notify" not in [
        s.name for s in NotifyingExecutor(_Inner(), enabled=True, client="mobile").specs()
    ]
    # web / 空 client(默认端)→ 暴露。
    assert "notify" in [
        s.name for s in NotifyingExecutor(_Inner(), enabled=True, client="web").specs()
    ]
    assert "notify" in [
        s.name for s in NotifyingExecutor(_Inner(), enabled=True, client="").specs()
    ]


async def test_mobile_rejects_execute():
    # specs 不暴露 + execute 门控双保险:mobile 即便 LLM 硬调 notify 也拒。
    ex = NotifyingExecutor(_Inner(), enabled=True, client="mobile")
    r = await ex.execute(ToolCall(id="1", name="notify", arguments={"title": "a", "body": "b"}))
    assert r.is_error is True


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
