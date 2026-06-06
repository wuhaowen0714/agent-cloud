from __future__ import annotations

from pathlib import Path

import grpc

from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc
from agent_cloud_sandbox.tools import run_tool


class SandboxServicer(sandbox_pb2_grpc.SandboxServicer):
    def __init__(self, base_workdir: Path) -> None:
        self._base = Path(base_workdir)

    async def ExecTool(
        self, request: sandbox_pb2.ExecToolRequest, context: grpc.aio.ServicerContext
    ) -> sandbox_pb2.ExecToolResponse:
        content, is_error = run_tool(
            self._base, request.work_subdir, request.tool_name, request.arguments_json
        )
        return sandbox_pb2.ExecToolResponse(content=content, is_error=is_error)


async def create_server(
    base_workdir: Path, host: str = "localhost", port: int = 0
) -> tuple[grpc.aio.Server, int]:
    """创建并启动一个 aio gRPC 服务器,返回 (server, bound_port)。port=0 让系统分配。"""
    server = grpc.aio.server()
    sandbox_pb2_grpc.add_SandboxServicer_to_server(SandboxServicer(base_workdir), server)
    bound_port = server.add_insecure_port(f"{host}:{port}")
    await server.start()
    return server, bound_port
