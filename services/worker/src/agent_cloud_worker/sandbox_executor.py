from __future__ import annotations

import json

import grpc
from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc
from agent_cloud_common import ToolCall, ToolResult, ToolSpec, builtin_tool_specs


def filtered_tool_specs(enabled_tools: list[str]) -> list[ToolSpec]:
    """按 enabled_tools 收窄内置工具集;空列表=全部(兼容未配置 enabled_tools 的 agent)。
    保持内置顺序,未知名忽略。"""
    specs = builtin_tool_specs()
    if not enabled_tools:
        return specs
    allowed = set(enabled_tools)
    return [s for s in specs if s.name in allowed]


class SandboxToolExecutor:
    """ToolExecutor 实现:把工具调用通过 gRPC 下发给沙箱服务执行。

    这是 worker→sandbox 信任边界的客户端侧:只传 工具名 + 参数 + 工作目录,
    不传 LLM Key。``enabled_tools`` 决定暴露给 LLM 的工具子集(per-agent)。
    """

    def __init__(
        self, channel: grpc.aio.Channel, work_subdir: str, enabled_tools: list[str] | None = None
    ) -> None:
        self._stub = sandbox_pb2_grpc.SandboxStub(channel)
        self._work_subdir = work_subdir
        self._enabled_tools = list(enabled_tools or [])

    def specs(self) -> list[ToolSpec]:
        return filtered_tool_specs(self._enabled_tools)

    async def execute(self, call: ToolCall) -> ToolResult:
        try:
            resp = await self._stub.ExecTool(
                sandbox_pb2.ExecToolRequest(
                    call_id=call.id,
                    tool_name=call.name,
                    arguments_json=json.dumps(call.arguments),
                    work_subdir=self._work_subdir,
                )
            )
        except grpc.aio.AioRpcError as exc:
            # 沙箱不可达/RPC 失败时,转成错误结果交回模型,而不是让异常冒泡冲掉整个回合
            # (与 LocalToolExecutor 一致,best-effort,spec §10)。
            return ToolResult(
                call_id=call.id,
                content=f"sandbox RPC failed: {exc.code().name}",
                is_error=True,
            )
        return ToolResult(call_id=call.id, content=resp.content, is_error=resp.is_error)
