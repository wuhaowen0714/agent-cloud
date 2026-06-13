from __future__ import annotations

import asyncio
import hmac
from pathlib import Path

import grpc
from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc
from agent_cloud_common import MAX_GRPC_MESSAGE_BYTES

from agent_cloud_sandbox.pty_session import PtySession
from agent_cloud_sandbox.tools import (
    _resolve_within,
    run_read_binary,
    run_tool,
    run_write_binary,
)


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
        # run_tool 内部是阻塞的(subprocess 等输出)。直接在 async handler 里同步调用会冻结整个
        # gRPC 事件循环 → 同沙箱的 Terminal 与其它 ExecTool 全部卡住(线上"终端也卡"的根因)。
        # to_thread 把阻塞 IO 移出事件循环,恢复真正的并发。
        content, is_error = await asyncio.to_thread(
            run_tool, self._base, request.work_subdir, request.tool_name, request.arguments_json
        )
        return sandbox_pb2.ExecToolResponse(content=content, is_error=is_error)

    async def WriteBinary(
        self, request: sandbox_pb2.WriteBinaryRequest, context: grpc.aio.ServicerContext
    ) -> sandbox_pb2.WriteBinaryResponse:
        # ⚠️ 复制 ExecTool 的 token 校验(本文件注释明确要求:新增 RPC 必须复制,否则成为未鉴权
        # 旁路——可绕过模型直接往用户工作区写任意文件)。
        if self._token:
            md = dict(context.invocation_metadata() or ())
            if not hmac.compare_digest(md.get("x-sandbox-token", ""), self._token):
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid sandbox token")
        # 写盘是阻塞 IO,to_thread 移出事件循环(同 ExecTool:否则冻结 Terminal/其它 RPC)。
        result, is_error = await asyncio.to_thread(
            run_write_binary, self._base, request.work_subdir, request.path, request.content
        )
        if is_error:
            return sandbox_pb2.WriteBinaryResponse(path="", is_error=True, error=result)
        return sandbox_pb2.WriteBinaryResponse(path=result, is_error=False, error="")

    async def ReadBinary(
        self, request: sandbox_pb2.ReadBinaryRequest, context: grpc.aio.ServicerContext
    ) -> sandbox_pb2.ReadBinaryResponse:
        # ⚠️ 复制 ExecTool 的 token 校验(新增 RPC 必须复制,否则成为未鉴权旁路——可绕过模型
        # 读取用户工作区任意文件)。
        if self._token:
            md = dict(context.invocation_metadata() or ())
            if not hmac.compare_digest(md.get("x-sandbox-token", ""), self._token):
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid sandbox token")
        # 读盘是阻塞 IO,to_thread 移出事件循环(同 ExecTool/WriteBinary)。
        content, error = await asyncio.to_thread(
            run_read_binary, self._base, request.work_subdir, request.path
        )
        if error:
            return sandbox_pb2.ReadBinaryResponse(content=b"", is_error=True, error=error)
        return sandbox_pb2.ReadBinaryResponse(content=content, is_error=False, error="")

    async def Terminal(self, request_iterator, context: grpc.aio.ServicerContext):
        # ⚠️ 复制 ExecTool 的 token 校验(server.py 注释明确要求:新增 RPC 必须复制,
        # 否则成为未鉴权旁路)。
        if self._token:
            md = dict(context.invocation_metadata() or ())
            if not hmac.compare_digest(md.get("x-sandbox-token", ""), self._token):
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid sandbox token")
        # 首帧必须是 start(开 PTY)
        try:
            first = await request_iterator.__anext__()
        except StopAsyncIteration:
            return
        if first.WhichOneof("msg") != "start":
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "first message must be start")
        # work_subdir 经与 ExecTool 同款围栏(防 .. 逃逸出沙箱基目录)
        try:
            workdir = _resolve_within(self._base, first.start.work_subdir)
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid work_subdir")
        sess = PtySession(workdir, first.start.rows, first.start.cols)
        await sess.start()

        async def _pump_in() -> None:
            async for msg in request_iterator:
                kind = msg.WhichOneof("msg")
                if kind == "input":
                    await sess.write(msg.input)
                elif kind == "resize":
                    sess.resize(msg.resize.rows, msg.resize.cols)

        pump = asyncio.create_task(_pump_in())
        try:
            while True:
                data = await sess.read()
                if data == b"":  # 子进程退出
                    break
                yield sandbox_pb2.TerminalServerMsg(output=data)
            code = await sess.wait()
            yield sandbox_pb2.TerminalServerMsg(exit_code=code)
        finally:
            pump.cancel()
            await sess.close()


async def create_server(
    base_workdir: Path, host: str = "localhost", port: int = 0, token: str = ""
) -> tuple[grpc.aio.Server, int]:
    """创建并启动一个 aio gRPC 服务器,返回 (server, bound_port)。port=0 让系统分配。

    token 非空 → servicer 校验调用方 metadata x-sandbox-token;空 → 开放(向后兼容)。
    """
    # 接收上限设大:WriteBinary 要收图片字节(可能数 MB),gRPC 默认 4MiB 会 RESOURCE_EXHAUSTED
    # (worker 端 channel 已两侧开到 MAX_GRPC_MESSAGE_BYTES,但接收上限由本 server 自己说了算)。
    server = grpc.aio.server(
        options=[
            ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
            ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
        ]
    )
    sandbox_pb2_grpc.add_SandboxServicer_to_server(SandboxServicer(base_workdir, token), server)
    bound_port = server.add_insecure_port(f"{host}:{port}")
    await server.start()
    return server, bound_port
