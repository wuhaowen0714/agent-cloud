from __future__ import annotations

import json

import grpc

from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc
from agent_cloud_common import ToolCall, ToolResult, ToolSpec, builtin_tool_specs


class SandboxToolExecutor:
    """ToolExecutor 实现:把工具调用通过 gRPC 下发给沙箱服务执行。

    这是 worker→sandbox 信任边界的客户端侧:只传 工具名 + 参数 + 工作目录,
    不传 LLM Key。
    """

    def __init__(self, channel: grpc.aio.Channel, work_subdir: str) -> None:
        self._stub = sandbox_pb2_grpc.SandboxStub(channel)
        self._work_subdir = work_subdir

    def specs(self) -> list[ToolSpec]:
        return builtin_tool_specs()

    async def execute(self, call: ToolCall) -> ToolResult:
        resp = await self._stub.ExecTool(
            sandbox_pb2.ExecToolRequest(
                call_id=call.id,
                tool_name=call.name,
                arguments_json=json.dumps(call.arguments),
                work_subdir=self._work_subdir,
            )
        )
        return ToolResult(call_id=call.id, content=resp.content, is_error=resp.is_error)
