import grpc
import pytest
from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc
from agent_cloud_sandbox.server import create_server


async def _exec(port, token_md):
    md = (("x-sandbox-token", token_md),) if token_md is not None else ()
    async with grpc.aio.insecure_channel(f"localhost:{port}") as ch:
        stub = sandbox_pb2_grpc.SandboxStub(ch)
        return await stub.ExecTool(
            sandbox_pb2.ExecToolRequest(
                call_id="t",
                tool_name="bash",
                arguments_json='{"command": "echo hi"}',
                work_subdir=".",
            ),
            metadata=md,
        )


async def test_token_required_when_configured(tmp_path):
    server, port = await create_server(tmp_path, host="localhost", port=0, token="sekret")
    try:
        resp = await _exec(port, "sekret")
        assert resp.is_error is False
        with pytest.raises(grpc.aio.AioRpcError) as ei:
            await _exec(port, "wrong")
        assert ei.value.code() == grpc.StatusCode.UNAUTHENTICATED
        with pytest.raises(grpc.aio.AioRpcError) as ei2:
            await _exec(port, None)  # 不带 metadata
        assert ei2.value.code() == grpc.StatusCode.UNAUTHENTICATED
    finally:
        await server.stop(None)


async def test_no_token_means_open(tmp_path):
    # 向后兼容:未配 token → 不校验(inprocess/CI/旧镜像)
    server, port = await create_server(tmp_path, host="localhost", port=0)
    try:
        resp = await _exec(port, None)
        assert resp.is_error is False
    finally:
        await server.stop(None)


async def _write_binary(port, token_md, *, content=b"\x89PNG\r\n\x1a\n\xff\x00\xfe"):
    md = (("x-sandbox-token", token_md),) if token_md is not None else ()
    async with grpc.aio.insecure_channel(f"localhost:{port}") as ch:
        stub = sandbox_pb2_grpc.SandboxStub(ch)
        return await stub.WriteBinary(
            sandbox_pb2.WriteBinaryRequest(
                path="media/picture/x.png", content=content, work_subdir="."
            ),
            metadata=md,
        )


async def test_write_binary_token_enforced_and_writes(tmp_path):
    # 新增 RPC 必须同样受 token 保护(否则成为未鉴权的任意写文件旁路),且落地是原始二进制。
    server, port = await create_server(tmp_path, host="localhost", port=0, token="sekret")
    try:
        png = b"\x89PNG\r\n\x1a\n\xff\x00\xfedata\x01\x02"
        resp = await _write_binary(port, "sekret", content=png)
        assert resp.is_error is False
        assert resp.path == "media/picture/x.png"
        assert (tmp_path / "media" / "picture" / "x.png").read_bytes() == png
        # 错误 token / 无 token 一律被拒
        with pytest.raises(grpc.aio.AioRpcError) as ei:
            await _write_binary(port, "wrong")
        assert ei.value.code() == grpc.StatusCode.UNAUTHENTICATED
        with pytest.raises(grpc.aio.AioRpcError) as ei2:
            await _write_binary(port, None)
        assert ei2.value.code() == grpc.StatusCode.UNAUTHENTICATED
    finally:
        await server.stop(None)
