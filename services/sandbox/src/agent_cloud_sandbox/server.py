from __future__ import annotations

import hmac
from pathlib import Path

import grpc
from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc

from agent_cloud_sandbox.tools import run_tool


class SandboxServicer(sandbox_pb2_grpc.SandboxServicer):
    def __init__(self, base_workdir: Path, token: str = "") -> None:
        self._base = Path(base_workdir)
        self._token = token

    async def ExecTool(
        self, request: sandbox_pb2.ExecToolRequest, context: grpc.aio.ServicerContext
    ) -> sandbox_pb2.ExecToolResponse:
        # 纵深防御:即便网络隔离被绕过(连到了沙箱端口),无对方 token 也调不动 ExecTool。
        # token 为空 = 不校验(向后兼容 inprocess/CI/旧镜像)。servicer 内 abort 可靠
        # 产出 trailing status(不同于 aio 拦截器返回的 handler 里 abort 会变 UNKNOWN)。
        # ⚠️ 本服务若日后新增 RPC,必须复制此 token 校验(否则成为未鉴权的旁路)。
        if self._token:
            md = dict(context.invocation_metadata() or ())
            if not hmac.compare_digest(md.get("x-sandbox-token", ""), self._token):
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid sandbox token")
        content, is_error = run_tool(
            self._base, request.work_subdir, request.tool_name, request.arguments_json
        )
        return sandbox_pb2.ExecToolResponse(content=content, is_error=is_error)


async def create_server(
    base_workdir: Path, host: str = "localhost", port: int = 0, token: str = ""
) -> tuple[grpc.aio.Server, int]:
    """创建并启动一个 aio gRPC 服务器,返回 (server, bound_port)。port=0 让系统分配。

    token 非空 → servicer 校验调用方 metadata x-sandbox-token;空 → 开放(向后兼容)。
    """
    server = grpc.aio.server()
    sandbox_pb2_grpc.add_SandboxServicer_to_server(SandboxServicer(base_workdir, token), server)
    bound_port = server.add_insecure_port(f"{host}:{port}")
    await server.start()
    return server, bound_port
