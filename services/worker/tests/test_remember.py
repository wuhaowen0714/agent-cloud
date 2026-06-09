from agent_cloud_common import ToolCall, ToolResult, ToolSpec
from agent_cloud_worker.remember import RememberingExecutor, remember_enabled


class _Inner:
    """最小内层 executor:一个 bash spec + 回显 execute。"""

    def specs(self):
        return [ToolSpec(name="bash", description="", input_schema={})]

    async def execute(self, call):
        return ToolResult(call_id=call.id, content=f"ran {call.name}", is_error=False)


def test_remember_enabled_logic():
    assert remember_enabled([]) is True  # 空 = 全部
    assert remember_enabled(["remember", "bash"]) is True
    assert remember_enabled(["bash"]) is False


def test_specs_include_remember_only_when_enabled():
    assert "remember" in [s.name for s in RememberingExecutor(_Inner(), enabled=True).specs()]
    assert "remember" not in [s.name for s in RememberingExecutor(_Inner(), enabled=False).specs()]
    # 内层工具始终保留
    assert "bash" in [s.name for s in RememberingExecutor(_Inner(), enabled=True).specs()]


async def test_remember_intercepted_not_forwarded():
    ex = RememberingExecutor(_Inner(), enabled=True)
    r = await ex.execute(
        ToolCall(id="1", name="remember", arguments={"content": "likes tea", "scope": "user"})
    )
    assert r.is_error is False
    assert "Remembered" in r.content  # 合成结果,没有"ran remember"(没进内层/沙箱)


async def test_non_remember_delegates_to_inner():
    ex = RememberingExecutor(_Inner(), enabled=True)
    r = await ex.execute(ToolCall(id="2", name="bash", arguments={"command": "ls"}))
    assert r.content == "ran bash"


async def test_validates_content_and_scope():
    ex = RememberingExecutor(_Inner(), enabled=True)
    blank = await ex.execute(ToolCall(id="1", name="remember", arguments={"content": "  "}))
    bad_scope = await ex.execute(
        ToolCall(id="2", name="remember", arguments={"content": "x", "scope": "bogus"})
    )
    assert blank.is_error
    assert bad_scope.is_error


async def test_disabled_rejects_remember_call():
    ex = RememberingExecutor(_Inner(), enabled=False)
    r = await ex.execute(ToolCall(id="1", name="remember", arguments={"content": "x"}))
    assert r.is_error is True
