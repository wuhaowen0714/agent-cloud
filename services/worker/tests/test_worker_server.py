import grpc
import pytest_asyncio
from agent_cloud.v1 import worker_pb2, worker_pb2_grpc
from agent_cloud_common import CompletionResult, Message, Role, ToolCall, Usage
from agent_cloud_sandbox.server import create_server as create_sandbox_server
from agent_cloud_worker.provider import FakeProvider
from agent_cloud_worker.server import create_server as create_worker_server


@pytest_asyncio.fixture
async def sandbox(tmp_path):
    server, port = await create_sandbox_server(base_workdir=tmp_path, host="localhost", port=0)
    yield f"localhost:{port}", tmp_path
    await server.stop(None)


def _call(tool, args):
    return CompletionResult(
        message=Message(
            role=Role.ASSISTANT, tool_calls=[ToolCall(id="c1", name=tool, arguments=args)]
        ),
        usage=Usage(input_tokens=3, output_tokens=4),
    )


def _final(text):
    return CompletionResult(
        message=Message(role=Role.ASSISTANT, text=text),
        usage=Usage(input_tokens=3, output_tokens=4),
    )


async def test_run_turn_over_grpc_executes_tool(sandbox):
    sandbox_addr, base = sandbox
    provider = FakeProvider(
        [
            _call("write_file", {"path": "hello.txt", "content": "from-agent"}),
            _final("done"),
        ]
    )
    worker_server, wport = await create_worker_server(
        provider_factory=lambda model, provider_name, key_ref: provider,
        host="localhost",
        port=0,
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            resp = await stub.RunTurn(
                worker_pb2.RunTurnRequest(
                    session_id="s1",
                    user_id="u1",
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    documents=[worker_pb2.Doc(scope="user", type="USER", content="# u")],
                    messages=[],
                    user_message="write the file",
                    sandbox_endpoint=sandbox_addr,
                    work_subdir="s1",
                )
            )
    finally:
        await worker_server.stop(None)

    assert resp.stop_reason == "end_turn"
    assert [m.role for m in resp.new_messages] == ["assistant", "tool", "assistant"]
    assert resp.output_tokens == 8  # 两次 provider 调用累加
    assert (base / "s1" / "hello.txt").read_text() == "from-agent"


async def test_run_turn_history_passed_through(sandbox):
    sandbox_addr, _ = sandbox
    provider = FakeProvider([_final("ok")])
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider,
        host="localhost",
        port=0,
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            resp = await stub.RunTurn(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    messages=[
                        worker_pb2.Msg(role="user", text="earlier"),
                        worker_pb2.Msg(role="assistant", text="reply"),
                    ],
                    user_message="now",
                    sandbox_endpoint=sandbox_addr,
                    work_subdir="s1",
                )
            )
    finally:
        await worker_server.stop(None)
    assert resp.stop_reason == "end_turn"
    assert len(resp.new_messages) == 1 and resp.new_messages[0].text == "ok"
