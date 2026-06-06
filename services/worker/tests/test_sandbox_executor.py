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
        message=Message(role=Role.ASSISTANT,
                        tool_calls=[ToolCall(id="c1", name=tool, arguments=args)]),
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def _final(text):
    return CompletionResult(message=Message(role=Role.ASSISTANT, text=text),
                            usage=Usage(input_tokens=1, output_tokens=1))


async def test_specs_match_catalog(sandbox):
    addr, _ = sandbox
    async with grpc.aio.insecure_channel(addr) as channel:
        ex = SandboxToolExecutor(channel, work_subdir="s1")
        assert {s.name for s in ex.specs()} == {"bash", "write_file", "read_file"}


async def test_run_turn_executes_tool_across_grpc(sandbox):
    addr, base = sandbox
    provider = FakeProvider([
        _call("write_file", {"path": "hello.txt", "content": "from-agent"}),
        _final("done"),
    ])
    async with grpc.aio.insecure_channel(addr) as channel:
        ex = SandboxToolExecutor(channel, work_subdir="s1")
        result = await run_turn(provider, ex, system="", history=[], user_message="write it")
    assert result.stop_reason == "end_turn"
    assert [m.role for m in result.new_messages] == [Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]
    assert result.new_messages[1].tool_results[0].is_error is False
    # 工具真的在沙箱的 work_subdir 下执行了
    assert (base / "s1" / "hello.txt").read_text() == "from-agent"
