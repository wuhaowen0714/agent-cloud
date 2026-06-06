import grpc
import pytest_asyncio
from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc
from agent_cloud_sandbox.server import create_server


@pytest_asyncio.fixture
async def sandbox(tmp_path):
    server, port = await create_server(base_workdir=tmp_path, host="localhost", port=0)
    yield f"localhost:{port}", tmp_path
    await server.stop(None)


async def test_exec_tool_over_grpc(sandbox):
    addr, base = sandbox
    async with grpc.aio.insecure_channel(addr) as channel:
        stub = sandbox_pb2_grpc.SandboxStub(channel)
        resp = await stub.ExecTool(
            sandbox_pb2.ExecToolRequest(
                call_id="c1",
                tool_name="write_file",
                arguments_json='{"path": "out.txt", "content": "data"}',
                work_subdir="s1",
            )
        )
    assert resp.is_error is False
    assert (base / "s1" / "out.txt").read_text() == "data"


async def test_exec_tool_error_over_grpc(sandbox):
    addr, _ = sandbox
    async with grpc.aio.insecure_channel(addr) as channel:
        stub = sandbox_pb2_grpc.SandboxStub(channel)
        resp = await stub.ExecTool(
            sandbox_pb2.ExecToolRequest(
                call_id="c1",
                tool_name="nope",
                arguments_json="{}",
                work_subdir="s1",
            )
        )
    assert resp.is_error is True
    assert "unknown tool" in resp.content.lower()


async def test_bash_output_clean_of_fork_noise_over_grpc(sandbox):
    # When bash forks a subprocess inside the aio server, gRPC emits fork/poll/Ixxxx
    # lines to the child's stderr. Run `echo hi` THROUGH the running server and assert
    # the payload is clean stdout, not contaminated by that noise. #3
    addr, _ = sandbox
    async with grpc.aio.insecure_channel(addr) as channel:
        stub = sandbox_pb2_grpc.SandboxStub(channel)
        resp = await stub.ExecTool(
            sandbox_pb2.ExecToolRequest(
                call_id="c1",
                tool_name="bash",
                arguments_json='{"command": "echo hi"}',
                work_subdir="s1",
            )
        )
    assert resp.is_error is False
    assert resp.content == "hi\n"
    for noise in ("fork", "poll", "FD from fork"):
        assert noise not in resp.content
