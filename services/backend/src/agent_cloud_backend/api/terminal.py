from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid

import grpc
from agent_cloud.v1 import sandbox_pb2, worker_pb2_grpc
from fastapi import APIRouter, Depends, WebSocket

from agent_cloud_backend.auth.security import decode_access_token
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.repositories.sandbox_registry import SandboxRegistryRepository
from agent_cloud_backend.repositories.user import UserRepository
from agent_cloud_backend.sandbox.deps import get_sandbox_manager
from agent_cloud_backend.sandbox.manager import SandboxConn, SandboxManager

router = APIRouter(tags=["terminal"])

_MAX_MSG = 16 * 1024 * 1024
_TOUCH_INTERVAL = 10.0  # 续租节流:键盘活动最多每 10s touch 一次,防过频写库

# 多终端:每用户至多 _MAX_TERMINALS_PER_USER 个并发终端(进程内表)。沙箱每条 Terminal
# 流是独立 PtySession,技术上不限;此软上限护住沙箱 pids_limit(开太多 bash 会撑满),超限
# 给前端清晰提示(close 4002)而非拖垮沙箱。多副本部署下各副本各持一份(上限按副本计,
# v1 单副本可接受);真正的资源闸仍是沙箱 per-user 复用 + 续租回收。
_MAX_TERMINALS_PER_USER = 5
_active_terminals: dict[uuid.UUID, set[WebSocket]] = {}


def _register(user_id: uuid.UUID, ws: WebSocket) -> bool:
    """登记新终端。该用户已达上限返回 False(调用方关闭并提示);否则加入返回 True。"""
    conns = _active_terminals.setdefault(user_id, set())
    if len(conns) >= _MAX_TERMINALS_PER_USER:
        return False
    conns.add(ws)
    return True


def _release(user_id: uuid.UUID, ws: WebSocket) -> None:
    """连接结束时摘除登记;该用户终端集合空了就删键。"""
    conns = _active_terminals.get(user_id)
    if conns is not None:
        conns.discard(ws)
        if not conns:
            del _active_terminals[user_id]


def _token_from_subprotocols(raw: str) -> str | None:
    """从 Sec-WebSocket-Protocol 头取 token。浏览器 WS 不能带 Authorization header,
    故 token 走 subprotocol:`["bearer", <access_token>]`。格式不符返回 None。"""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) >= 2 and parts[0] == "bearer":
        return parts[1]
    return None


async def _pump_ws_to_worker(ws, call, on_activity=None) -> None:
    """浏览器 → worker:二进制帧 = 键盘输入;文本帧 = resize(JSON {rows,cols})。
    每个 input/resize 帧触发 on_activity(若提供)——端点据此续租沙箱(第二档:
    只认用户活动,纯输出不续)。"""
    while True:
        msg = await ws.receive()
        if msg.get("type") == "websocket.disconnect":
            return
        b = msg.get("bytes")
        if b is not None:
            await call.write(sandbox_pb2.TerminalClientMsg(input=b))
            if on_activity is not None:
                await on_activity()
            continue
        t = msg.get("text")
        if t is not None:
            try:
                r = json.loads(t)
                # 钳到 1..65535:proto uint32 不接受负值、PTY 侧 struct.pack("H") 会溢出
                rows = max(1, min(65535, int(r["rows"])))
                cols = max(1, min(65535, int(r["cols"])))
                await call.write(
                    sandbox_pb2.TerminalClientMsg(
                        resize=sandbox_pb2.TerminalResize(rows=rows, cols=cols)
                    )
                )
                if on_activity is not None:
                    await on_activity()
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

    # 多终端:每用户至多 _MAX_TERMINALS_PER_USER 个并发终端;超限直接拒绝本连接(不动已有的),
    # 前端据 close code 4002 提示"已达上限",而非顶替别处的终端。
    if not _register(user.id, websocket):
        with contextlib.suppress(Exception):
            await websocket.close(code=4002, reason="terminal limit reached")
        return

    # 续租(第二档):用户活动(input/resize)节流 touch last_used_at,防 reaper 中途回收。
    last_touch = 0.0

    async def _on_activity() -> None:
        nonlocal last_touch
        now = time.monotonic()
        if now - last_touch < _TOUCH_INTERVAL:
            return
        last_touch = now
        with contextlib.suppress(Exception):
            async with get_sessionmaker()() as db:
                await SandboxRegistryRepository(db).touch_for_user(user.id)
                await db.commit()

    # 外层 try 覆盖沙箱获取/开流之后的一切,保证 _release 必达(否则 provision 失败会
    # 在 _active_terminals 留死登记,审查 L1)。
    try:
        conn = await manager.get_endpoint_for_user(user.id)
        # 终端工作目录 = 用户工作区根(与 agent/文件抽屉同一处,卖点:互相可见)。与 turn.py
        # 一致:docker 沙箱已把 <host>/<uid>/workspace 挂到 /workspace → work_subdir="."。
        # inprocess 下沙箱 base 已是 <base>/<uid>,故用 "workspace"(不带 uid 否则路径重复)。
        work_subdir = "." if settings.sandbox_provisioner == "docker" else "workspace"
        channel, call = _open_worker_terminal(settings.worker_endpoint, conn)
        try:
            await call.write(
                sandbox_pb2.TerminalClientMsg(
                    start=sandbox_pb2.TerminalStart(work_subdir=work_subdir, rows=24, cols=80)
                )
            )
            a = asyncio.create_task(_pump_ws_to_worker(websocket, call, _on_activity))
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
    finally:
        _release(user.id, websocket)
        with contextlib.suppress(Exception):
            await websocket.close()
