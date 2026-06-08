import grpc
import pytest_asyncio
from agent_cloud_common import CompletionResult, Message, Role, ToolCall, Usage
from agent_cloud_sandbox.server import create_server
from agent_cloud_worker.loop import run_turn
from agent_cloud_worker.provider import FakeProvider
from agent_cloud_worker.sandbox_executor import SandboxToolExecutor


@pytest_asyncio.fixture
async def sandbox(tmp_path):
    server, port = await create_server(base_workdir=tmp_path, host="localhost", port=0)
    yield f"localhost:{port}", tmp_path
    await server.stop(None)


def _call(tool, args):
    return CompletionResult(
        message=Message(
            role=Role.ASSISTANT, tool_calls=[ToolCall(id="c1", name=tool, arguments=args)]
        ),
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def _final(text):
    return CompletionResult(
        message=Message(role=Role.ASSISTANT, text=text),
        usage=Usage(input_tokens=1, output_tokens=1),
    )


async def test_specs_match_catalog(sandbox):
    addr, _ = sandbox
    async with grpc.aio.insecure_channel(addr) as channel:
        ex = SandboxToolExecutor(channel, work_subdir="s1")
        assert {s.name for s in ex.specs()} == {"bash", "write_file", "read_file", "edit"}


async def test_run_turn_executes_tool_across_grpc(sandbox):
    addr, base = sandbox
    provider = FakeProvider(
        [
            _call("write_file", {"path": "hello.txt", "content": "from-agent"}),
            _final("done"),
        ]
    )
    async with grpc.aio.insecure_channel(addr) as channel:
        ex = SandboxToolExecutor(channel, work_subdir="s1")
        result = await run_turn(provider, ex, system="", history=[], user_message="write it")
    assert result.stop_reason == "end_turn"
    assert [m.role for m in result.new_messages] == [Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]
    assert result.new_messages[1].tool_results[0].is_error is False
    # 工具真的在沙箱的 work_subdir 下执行了
    assert (base / "s1" / "hello.txt").read_text() == "from-agent"


async def test_error_response_maps_to_tool_result(sandbox):
    # A normal (non-RPC-level) error from the sandbox — e.g. unknown tool — must be
    # carried through as is_error=True on the ToolResult, not swallowed.
    addr, _ = sandbox
    async with grpc.aio.insecure_channel(addr) as channel:
        ex = SandboxToolExecutor(channel, work_subdir="s1")
        result = await ex.execute(ToolCall(id="c1", name="nope", arguments={}))
    assert result.is_error is True
    assert result.call_id == "c1"
    assert "unknown tool" in result.content.lower()


async def test_dead_sandbox_returns_error_not_exception():
    # localhost:1 is unreachable -> ExecTool raises AioRpcError under the hood.
    # The executor must convert that into is_error=True, mirroring LocalToolExecutor,
    # rather than letting the exception propagate and crash the turn (spec §10).
    async with grpc.aio.insecure_channel("localhost:1") as channel:
        ex = SandboxToolExecutor(channel, work_subdir="s1", max_attempts=1)
        result = await ex.execute(ToolCall(id="c1", name="bash", arguments={"command": "echo hi"}))
    assert result.is_error is True
    assert result.call_id == "c1"
    assert "sandbox RPC failed" in result.content


async def test_run_turn_survives_dead_sandbox():
    # A dead sandbox must not crash the whole turn: the model gets the error result
    # as a TOOL message and is free to decide what to do next.
    provider = FakeProvider(
        [
            _call("bash", {"command": "echo hi"}),
            _final("recovered"),
        ]
    )
    async with grpc.aio.insecure_channel("localhost:1") as channel:
        ex = SandboxToolExecutor(channel, work_subdir="s1", max_attempts=1)
        result = await run_turn(provider, ex, system="", history=[], user_message="run it")
    assert result.stop_reason == "end_turn"
    assert [m.role for m in result.new_messages] == [Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]
    assert result.new_messages[1].tool_results[0].is_error is True


class _Unavailable(grpc.aio.AioRpcError):
    def __init__(self):
        pass  # 跳过父类 init,只需 code()

    def code(self):
        return grpc.StatusCode.UNAVAILABLE


class _Resp:
    content = "ok"
    is_error = False


async def test_execute_retries_unavailable_then_succeeds():
    # docker 沙箱冷启动期短暂 UNAVAILABLE → 重试遮掉(spec §4.1)。
    class _Stub:
        def __init__(self, fail_times):
            self.fail_times = fail_times
            self.calls = 0

        async def ExecTool(self, req):
            self.calls += 1
            if self.calls <= self.fail_times:
                raise _Unavailable()
            return _Resp()

    ex = SandboxToolExecutor(channel=None, work_subdir=".", max_attempts=5, retry_backoff=0.0)
    ex._stub = _Stub(fail_times=2)
    res = await ex.execute(ToolCall(id="c1", name="bash", arguments={"command": "echo hi"}))
    assert res.is_error is False and res.content == "ok"
    assert ex._stub.calls == 3


async def test_execute_gives_up_after_max_attempts():
    class _Stub:
        def __init__(self):
            self.calls = 0

        async def ExecTool(self, req):
            self.calls += 1
            raise _Unavailable()

    ex = SandboxToolExecutor(channel=None, work_subdir=".", max_attempts=3, retry_backoff=0.0)
    ex._stub = _Stub()
    res = await ex.execute(ToolCall(id="c1", name="bash", arguments={"command": "x"}))
    assert res.is_error is True and "UNAVAILABLE" in res.content
    assert ex._stub.calls == 3
