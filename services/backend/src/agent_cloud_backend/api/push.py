"""手机推送通道:app 前台服务的 WebSocket 长连接(自建,零第三方推送依赖)。

国内无 GMS 设备收不到 FCM、厂商通道要企业资质,故走自建:app 保持一条 WS 长连,
backend 有事(agent notify / 定时任务完成)就下发 JSON,app 弹本地系统通知。
单实例部署(st-e 单 backend),连接注册表放进程内即可。

鉴权同 terminal:token 走 Sec-WebSocket-Protocol(["bearer", <access_token>]),
握手后服务端以 "bearer" 子协议 accept。
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from agent_cloud_backend.auth import security
from agent_cloud_backend.auth.security import decode_access_token
from agent_cloud_backend.config import get_settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.repositories.refresh_token import RefreshTokenRepository
from agent_cloud_backend.repositories.user import UserRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/push", tags=["push"])

# user_id → 该用户的活跃推送连接(一人可多设备)。进程内单实例即可。
_conns: dict[uuid.UUID, set[WebSocket]] = {}


def _token_from_subprotocols(raw: str) -> tuple[str, str] | None:
    """返回 (scheme, token)。scheme: "bearer"=access JWT(15min,web/调试用),
    "refresh"=refresh token(30d,app 前台服务用——它拿不到新 access:主 app 不在前台
    时拦截器不刷新,且 refresh 是严格轮换+双花全吊销,FGS 绝不能自己去换发;故 WS 鉴权
    直接【验证】refresh(hash 查表,不消耗不轮换),主 app 活跃时轮换的新 refresh 会落
    回 secure_storage,FGS 每次重连重读即自动跟上)。"""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) == 2 and parts[0] in ("bearer", "refresh"):
        return parts[0], parts[1]
    return None


async def push_to_user(user_id: uuid.UUID, payload: dict) -> int:
    """给该用户所有在线设备下发一条推送。返回送达连接数(0=没有设备在线,静默)。
    发送失败的连接就地清理(设备网络切换/进程被杀后的半死连接)。"""
    delivered = 0
    for ws in list(_conns.get(user_id, ())):
        try:
            await ws.send_json(payload)
            delivered += 1
        except Exception:
            _conns.get(user_id, set()).discard(ws)
    return delivered


async def _authenticate(scheme: str, token: str) -> uuid.UUID | None:
    """两种凭证换 user_id(UUID);校验用户仍存在(防已删用户保持通道)。"""
    from datetime import UTC, datetime

    settings = get_settings()
    if scheme == "bearer":
        raw = decode_access_token(token, secret=settings.auth_secret)
        if raw is None:
            return None
        uid = uuid.UUID(raw)  # JWT sub 是 str,注册表/推送侧统一 UUID(审查 HIGH-1)
    else:  # refresh:hash 查表验证,不消耗不轮换
        async with get_sessionmaker()() as db:
            row = await RefreshTokenRepository(db).get_by_hash(security.hash_refresh(token))
            if row is None or row.revoked_at is not None:
                return None
            if row.expires_at <= datetime.now(UTC):
                return None
            uid = row.user_id
    async with get_sessionmaker()() as db:
        if await UserRepository(db).get(uid) is None:
            return None
    return uid


@router.websocket("/ws")
async def push_ws(websocket: WebSocket):
    parsed = _token_from_subprotocols(websocket.headers.get("sec-websocket-protocol", ""))
    uid = await _authenticate(*parsed) if parsed else None
    if uid is None:
        # 未鉴权:握手前拒绝(1008 policy violation)
        await websocket.close(code=1008)
        return
    await websocket.accept(subprotocol=parsed[0])
    _conns.setdefault(uid, set()).add(websocket)
    logger.info("push ws connected: user=%s conns=%d", uid, len(_conns[uid]))
    try:
        while True:
            # 客户端应用层心跳(NAT 保活);其余消息忽略。断开抛 WebSocketDisconnect。
            msg = await websocket.receive_json()
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("push ws errored for user %s", uid)
    finally:
        conns = _conns.get(uid)
        if conns is not None:
            conns.discard(websocket)
            if not conns:
                _conns.pop(uid, None)
