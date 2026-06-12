from __future__ import annotations

import asyncio
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
        self,
        channel: grpc.aio.Channel,
        work_subdir: str,
        enabled_tools: list[str] | None = None,
        max_attempts: int = 10,
        retry_backoff: float = 1.0,
        token: str = "",
        exec_timeout: float = 360.0,
    ) -> None:
        self._stub = sandbox_pb2_grpc.SandboxStub(channel) if channel is not None else None
        self._work_subdir = work_subdir
        self._enabled_tools = list(enabled_tools or [])
        # 沙箱 gRPC 鉴权:token 经 metadata 带给沙箱拦截校验(空=沙箱开放,inprocess/旧)。
        self._md = (("x-sandbox-token", token),) if token else None
        # 沙箱(尤其 docker 冷启动)可能短暂 UNAVAILABLE:对其重试,与首个 LLM 思考重叠
        # 以隐藏冷启动(spec §4.1)。其它错误立即转成 is_error 结果。
        self._max_attempts = max_attempts
        self._retry_backoff = retry_backoff
        # ExecTool RPC 客户端超时:略大于沙箱端 bash 硬上限(默认 300s)作纵深兜底——沙箱整体
        # 无响应(非单命令卡)时不让 worker 无限等(终端路径已有 channel_ready 兜底,ExecTool
        # 此前没有)。超时 → DEADLINE_EXCEEDED(非 UNAVAILABLE 不重试)→ 转 is_error 交回模型。
        self._exec_timeout = exec_timeout

    def specs(self) -> list[ToolSpec]:
        return filtered_tool_specs(self._enabled_tools)

    async def execute(self, call: ToolCall) -> ToolResult:
        # 在 worker(可信侧)强制 enabled_tools:不只是从 prompt 隐藏。否则 skill 的
        # SKILL.md(不可信内容)可诱导模型调用被禁用的工具(如 bash)。空集=全部放行。
        if self._enabled_tools and call.name not in self._enabled_tools:
            return ToolResult(
                call_id=call.id,
                content=f"tool not enabled for this agent: {call.name}",
                is_error=True,
            )
        req = sandbox_pb2.ExecToolRequest(
            call_id=call.id,
            tool_name=call.name,
            arguments_json=json.dumps(call.arguments),
            work_subdir=self._work_subdir,
        )
        for attempt in range(self._max_attempts):
            try:
                resp = await self._stub.ExecTool(
                    req, metadata=self._md, timeout=self._exec_timeout
                )
                return ToolResult(call_id=call.id, content=resp.content, is_error=resp.is_error)
            except grpc.aio.AioRpcError as exc:
                # 冷启动期的 UNAVAILABLE 重试;其它错误立即转成 is_error 结果交回模型
                # (不让异常冒泡冲掉整个回合,与 LocalToolExecutor 一致,spec §10)。
                if exc.code() == grpc.StatusCode.UNAVAILABLE and attempt < self._max_attempts - 1:
                    await asyncio.sleep(self._retry_backoff)
                    continue
                return ToolResult(
                    call_id=call.id,
                    content=f"sandbox RPC failed: {exc.code().name}",
                    is_error=True,
                )
