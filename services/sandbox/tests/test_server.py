import asyncio

import grpc
import pytest
import pytest_asyncio
from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc
from agent_cloud_common import MAX_GRPC_MESSAGE_BYTES
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


async def test_terminal_echo_over_grpc(sandbox):
    # 完整 gRPC 链路:开 PTY → 敲命令 → 收到含输出的 output 帧
    addr, _ = sandbox
    async with grpc.aio.insecure_channel(addr) as channel:
        stub = sandbox_pb2_grpc.SandboxStub(channel)
        call = stub.Terminal()
        await call.write(
            sandbox_pb2.TerminalClientMsg(
                start=sandbox_pb2.TerminalStart(work_subdir="s1", rows=24, cols=80)
            )
        )
        await call.write(sandbox_pb2.TerminalClientMsg(input=b"echo term-ok\n"))
        buf = b""
        async with asyncio.timeout(5):
            while b"term-ok" not in buf:
                msg = await call.read()
                if msg.WhichOneof("msg") == "output":
                    buf += msg.output
        assert b"term-ok" in buf
        await call.done_writing()
        call.cancel()


async def test_terminal_first_msg_must_be_start(sandbox):
    addr, _ = sandbox
    async with grpc.aio.insecure_channel(addr) as channel:
        stub = sandbox_pb2_grpc.SandboxStub(channel)
        call = stub.Terminal()
        await call.write(sandbox_pb2.TerminalClientMsg(input=b"oops\n"))  # 非 start
        await call.done_writing()
        with pytest.raises(grpc.aio.AioRpcError) as ei:
            async for _ in call:
                pass
    assert ei.value.code() == grpc.StatusCode.INVALID_ARGUMENT


async def test_terminal_exit_emits_exit_code(sandbox):
    addr, _ = sandbox
    async with grpc.aio.insecure_channel(addr) as channel:
        stub = sandbox_pb2_grpc.SandboxStub(channel)
        call = stub.Terminal()
        await call.write(
            sandbox_pb2.TerminalClientMsg(
                start=sandbox_pb2.TerminalStart(work_subdir="s1", rows=24, cols=80)
            )
        )
        await call.write(sandbox_pb2.TerminalClientMsg(input=b"exit 0\n"))
        exit_code = None
        async with asyncio.timeout(5):
            async for msg in call:
                if msg.WhichOneof("msg") == "exit_code":
                    exit_code = msg.exit_code
                    break
        assert exit_code == 0


async def test_write_binary_accepts_large_image(tmp_path):
    # 回归 H1:WriteBinary 收图片字节(可能数 MB),sandbox server 必须把接收上限开大,否则
    # gRPC 默认 4MiB 下大图 RESOURCE_EXHAUSTED 落盘失败。用 5MiB(> 默认 4MiB)穿真 server。
    server, port = await create_server(base_workdir=tmp_path, host="localhost", port=0)
    try:
        big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024)  # > 默认 4MiB
        async with grpc.aio.insecure_channel(
            f"localhost:{port}",
            options=[
                ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
                ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
            ],
        ) as channel:
            stub = sandbox_pb2_grpc.SandboxStub(channel)
            resp = await stub.WriteBinary(
                sandbox_pb2.WriteBinaryRequest(
                    path="media/picture/big.png", content=big, work_subdir="."
                )
            )
        assert resp.is_error is False
        assert (tmp_path / "media" / "picture" / "big.png").read_bytes() == big
    finally:
        await server.stop(None)


async def test_read_binary_roundtrip_over_grpc(tmp_path):
    # 写一张大图再 ReadBinary 读回 —— 穿真 server,逐字节相同。返回侧也可能数 MB,验证 server
    # 的 send 上限同样开大(图片编辑读输入图的链路)。
    server, port = await create_server(base_workdir=tmp_path, host="localhost", port=0)
    try:
        img = b"\x89PNG\r\n\x1a\n" + b"\xab\xcd" * (3 * 1024 * 1024)  # ~6MiB > 默认 4MiB
        async with grpc.aio.insecure_channel(
            f"localhost:{port}",
            options=[
                ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
                ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
            ],
        ) as channel:
            stub = sandbox_pb2_grpc.SandboxStub(channel)
            await stub.WriteBinary(
                sandbox_pb2.WriteBinaryRequest(
                    path="media/upload/in.png", content=img, work_subdir="."
                )
            )
            resp = await stub.ReadBinary(
                sandbox_pb2.ReadBinaryRequest(path="media/upload/in.png", work_subdir=".")
            )
        assert resp.is_error is False
        assert resp.content == img
    finally:
        await server.stop(None)


async def test_read_binary_missing_file_over_grpc(tmp_path):
    server, port = await create_server(base_workdir=tmp_path, host="localhost", port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{port}") as channel:
            stub = sandbox_pb2_grpc.SandboxStub(channel)
            resp = await stub.ReadBinary(
                sandbox_pb2.ReadBinaryRequest(path="nope.png", work_subdir=".")
            )
        assert resp.is_error is True
        assert "not a file" in resp.error
    finally:
        await server.stop(None)
