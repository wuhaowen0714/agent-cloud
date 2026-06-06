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
        assert {s.name for s in ex.specs()} == {"bash", "write_file", "read_file"}


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
        ex = SandboxToolExecutor(channel, work_subdir="s1")
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
        ex = SandboxToolExecutor(channel, work_subdir="s1")
        result = await run_turn(provider, ex, system="", history=[], user_message="run it")
    assert result.stop_reason == "end_turn"
    assert [m.role for m in result.new_messages] == [Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]
    assert result.new_messages[1].tool_results[0].is_error is True
