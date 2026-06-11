from __future__ import annotations

import asyncio
import contextlib
import json
import uuid

import grpc
from agent_cloud.v1 import sandbox_pb2, worker_pb2_grpc
from fastapi import APIRouter, Depends, WebSocket

from agent_cloud_backend.auth.security import decode_access_token
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.repositories.user import UserRepository
from agent_cloud_backend.sandbox.deps import get_sandbox_manager
from agent_cloud_backend.sandbox.manager import SandboxConn, SandboxManager

router = APIRouter(tags=["terminal"])

_MAX_MSG = 16 * 1024 * 1024


def _token_from_subprotocols(raw: str) -> str | None:
    """从 Sec-WebSocket-Protocol 头取 token。浏览器 WS 不能带 Authorization header,
    故 token 走 subprotocol:`["bearer", <access_token>]`。格式不符返回 None。"""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) >= 2 and parts[0] == "bearer":
        return parts[1]
    return None


async def _pump_ws_to_worker(ws, call) -> None:
    """浏览器 → worker:二进制帧 = 键盘输入;文本帧 = resize(JSON {rows,cols})。"""
    while True:
        msg = await ws.receive()
        if msg.get("type") == "websocket.disconnect":
            return
        b = msg.get("bytes")
        if b is not None:
            await call.write(sandbox_pb2.TerminalClientMsg(input=b))
            continue
        t = msg.get("text")
        if t is not None:
            try:
                r = json.loads(t)
                await call.write(
                    sandbox_pb2.TerminalClientMsg(
                        resize=sandbox_pb2.TerminalResize(rows=int(r["rows"]), cols=int(r["cols"]))
                    )
                )
            except (ValueError, KeyError, TypeError):
                pass  # 坏 resize 帧忽略,不拖垮终端


async def _pump_worker_to_ws(call, ws) -> None:
    """worker → 浏览器:output 帧转二进制下发;exit_code 帧 = shell 退出 → 关 WS。"""
    async for out in call:
        kind = out.WhichOneof("msg")
        if kind == "output":
            await ws.send_bytes(out.output)
        else:  # exit_code:shell 结束
            await ws.close(code=1000)
            return


def _open_worker_terminal(worker_endpoint: str, conn: SandboxConn):
    """开到 worker 的 Terminal 双向流:sandbox 连接信息走 gRPC metadata。
    返回 (channel, call)。channel 须在桥接结束后关闭。"""
    options = [
        ("grpc.max_send_message_length", _MAX_MSG),
        ("grpc.max_receive_message_length", _MAX_MSG),
    ]
    channel = grpc.aio.insecure_channel(worker_endpoint, options=options)
    stub = worker_pb2_grpc.WorkerStub(channel)
    call = stub.Terminal(
        metadata=(("x-sandbox-endpoint", conn.endpoint), ("x-sandbox-token", conn.token))
    )
    return channel, call


@router.websocket("/terminal")
async def terminal_ws(
    websocket: WebSocket,
    settings: Settings = Depends(get_settings),
    manager: SandboxManager = Depends(get_sandbox_manager),
) -> None:
    # 鉴权:subprotocol 取 token → 解析 user(JWT 签名校验)→ 查 user 存在(防已删用户)。
    # WS 不能带 header,故不复用 get_current_user 依赖;跨租户隔离靠用解析出的 uid 路由沙箱。
    token = _token_from_subprotocols(websocket.headers.get("sec-websocket-protocol", ""))
    uid = decode_access_token(token, secret=settings.auth_secret) if token else None
    if uid is None:
        await websocket.close(code=1008)
        return
    async with get_sessionmaker()() as db:
        user = await UserRepository(db).get(uuid.UUID(uid))
    if user is None:
        await websocket.close(code=1008)
        return
    await websocket.accept(subprotocol="bearer")  # 必须回显选中的 subprotocol

    conn = await manager.get_endpoint_for_user(user.id)
    # docker 沙箱已把用户 workspace 挂到 /workspace,work_subdir 用 "." 落在工作区根
    # (与 turn.py 一致);inprocess/测试用 <user_id>/workspace 相对沙箱 base。
    work_subdir = "." if settings.sandbox_provisioner == "docker" else f"{user.id}/workspace"
    channel, call = _open_worker_terminal(settings.worker_endpoint, conn)
    try:
        await call.write(
            sandbox_pb2.TerminalClientMsg(
                start=sandbox_pb2.TerminalStart(work_subdir=work_subdir, rows=24, cols=80)
            )
        )
        a = asyncio.create_task(_pump_ws_to_worker(websocket, call))
        b = asyncio.create_task(_pump_worker_to_ws(call, websocket))
        try:
            await asyncio.wait({a, b}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            a.cancel()
            b.cancel()
            with contextlib.suppress(Exception):
                await call.done_writing()
    finally:
        with contextlib.suppress(Exception):
            await channel.close()
        with contextlib.suppress(Exception):
            await websocket.close()
