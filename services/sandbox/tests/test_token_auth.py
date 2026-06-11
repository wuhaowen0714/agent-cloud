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
