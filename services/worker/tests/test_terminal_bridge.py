import asyncio

import grpc
import pytest_asyncio
from agent_cloud.v1 import sandbox_pb2, worker_pb2_grpc
from agent_cloud_sandbox.server import create_server as create_sandbox_server
from agent_cloud_worker.server import create_server as create_worker_server


@pytest_asyncio.fixture
async def sandbox(tmp_path):
    server, port = await create_sandbox_server(base_workdir=tmp_path, host="localhost", port=0)
    yield f"localhost:{port}"
    await server.stop(None)


@pytest_asyncio.fixture
async def worker():
    # provider_factory 不被终端用到,给个占位
    server, port = await create_worker_server(provider_factory=lambda *a: None, port=0)
    yield f"localhost:{port}"
    await server.stop(None)


async def test_terminal_bridge_echoes(sandbox, worker):
    # backend 视角:连 worker 的 Terminal,经 metadata 给 sandbox 连接信息;
    # worker 透传到真 sandbox PTY,敲命令应收到回显 output。
    async with grpc.aio.insecure_channel(worker) as ch:
        stub = worker_pb2_grpc.WorkerStub(ch)
        call = stub.Terminal(metadata=(("x-sandbox-endpoint", sandbox), ("x-sandbox-token", "")))
        await call.write(
            sandbox_pb2.TerminalClientMsg(
                start=sandbox_pb2.TerminalStart(work_subdir="s1", rows=24, cols=80)
            )
        )
        await call.write(sandbox_pb2.TerminalClientMsg(input=b"echo bridge-ok\n"))
        buf = b""
        async with asyncio.timeout(5):
            while b"bridge-ok" not in buf:
                msg = await call.read()
                if msg.WhichOneof("msg") == "output":
                    buf += msg.output
        assert b"bridge-ok" in buf
        await call.done_writing()
        call.cancel()


async def test_terminal_bridge_missing_endpoint(worker):
    # 无 sandbox endpoint metadata → INVALID_ARGUMENT
    async with grpc.aio.insecure_channel(worker) as ch:
        stub = worker_pb2_grpc.WorkerStub(ch)
        call = stub.Terminal()  # 无 metadata
        await call.write(
            sandbox_pb2.TerminalClientMsg(
                start=sandbox_pb2.TerminalStart(work_subdir="s1", rows=24, cols=80)
            )
        )
        await call.done_writing()
        import pytest

        with pytest.raises(grpc.aio.AioRpcError) as ei:
            async for _ in call:
                pass
    assert ei.value.code() == grpc.StatusCode.INVALID_ARGUMENT
