"""手机推送通道:app 前台服务的 WebSocket 长连接(自建,零第三方推送依赖)。

国内无 GMS 设备收不到 FCM、厂商通道要企业资质,故走自建:app 保持一条 WS 长连,
backend 有事(agent notify / 定时任务完成)就下发 JSON,app 弹本地系统通知。
单实例部署(st-e 单 backend),连接注册表放进程内即可。

可靠性(2026-07-07「8 点战报没推到」复盘):移动网络下长连必然偶断(部署重启/NAT
超时/VPN 切换/息屏管控),且半开连接的 send 会假成功 —— 所以送达不能依赖"连接恰好
活着"。事实源是 notifications 表(notify_apply/scheduler 先落库):
  - 下发消息带通知 id,app 弹出后回 {"type":"ack","id":...} 才标 delivered;
  - 重连(含首连)时把未送达的通知补投(最新 BACKLOG_LIMIT 条,更旧的放弃防轰炸);
  - 半开检测:app 侧 WebSocket.pingInterval + uvicorn --ws-ping-*(compose)双向探活。
web 端 15s 轮询同一张表并 mark-delivered,两端语义一致:delivered = 任一端已展示。

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
from agent_cloud_backend.repositories.notification import NotificationRepository
from agent_cloud_backend.repositories.refresh_token import RefreshTokenRepository
from agent_cloud_backend.repositories.user import UserRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/push", tags=["push"])

# user_id → 该用户的活跃推送连接(一人可多设备)。进程内单实例即可。
_conns: dict[uuid.UUID, set[WebSocket]] = {}

# 重连补投上限:只补最新 N 条 + 只补 MAX_AGE 内的,更旧的直接放弃(标 delivered)——
# 防短间隔任务(如 60s 提醒)断链一夜攒出上百条重连瞬间轰炸,也防上线时把历史积压
# (修复前攒的 148 条)当新通知弹出来。
BACKLOG_LIMIT = 20
BACKLOG_MAX_AGE_HOURS = 48


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


async def push_to_user(
    user_id: uuid.UUID, payload: dict, *, notification_id: uuid.UUID | None = None
) -> int:
    """给该用户所有在线设备下发一条推送。返回写出的连接数(0=没有设备在线,静默)。

    带 notification_id 时 payload 附带 "id",app 弹出后回 ack 才算真送达(这里的
    send 写进半开连接会假成功,不能作为送达依据);没 ack 的由重连补投兜底。
    发送失败的连接就地清理(设备网络切换/进程被杀后的半死连接)。"""
    if notification_id is not None:
        payload = {**payload, "id": str(notification_id)}
    delivered = 0
    for ws in list(_conns.get(user_id, ())):
        try:
            await ws.send_json(payload)
            delivered += 1
        except Exception:
            _conns.get(user_id, set()).discard(ws)
    logger.info(
        "push_to_user user=%s type=%s wrote=%d", user_id, payload.get("type"), delivered
    )
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


async def _send_backlog(websocket: WebSocket, uid: uuid.UUID) -> None:
    """连接建立即补投未送达通知(升序=按时间先后弹)。过期/超限的直接放弃标 delivered。
    发送失败往外抛,走端点的断链清理路径。"""
    from datetime import UTC, datetime, timedelta

    async with get_sessionmaker()() as db:
        repo = NotificationRepository(db)
        pending = await repo.list_undelivered(uid)
        cutoff = datetime.now(UTC) - timedelta(hours=BACKLOG_MAX_AGE_HOURS)
        fresh = [n for n in pending if n.created_at >= cutoff]
        if len(fresh) > BACKLOG_LIMIT:
            fresh = fresh[-BACKLOG_LIMIT:]
        dropped = [n for n in pending if n not in fresh]
        if dropped:
            await repo.mark_delivered([n.id for n in dropped], uid)
            await db.commit()
            logger.info("push backlog dropped: user=%s count=%d", uid, len(dropped))
        pending = fresh
        # commit 前取纯数据,出了 session 不碰 ORM 对象(expire_on_commit 防御)
        items = [
            {
                "type": "notify",
                "id": str(n.id),
                "title": n.title,
                "body": n.body,
                "session_id": str(n.origin_session_id) if n.origin_session_id else None,
            }
            for n in pending
        ]
    for item in items:
        await websocket.send_json(item)
    if items:
        logger.info("push backlog sent: user=%s count=%d", uid, len(items))


async def _mark_acked(uid: uuid.UUID, raw_id: object) -> None:
    """app 送达回执 → 标 delivered(带归属校验)。坏 id 忽略。"""
    try:
        nid = uuid.UUID(str(raw_id))
    except (ValueError, TypeError):
        return
    async with get_sessionmaker()() as db:
        await NotificationRepository(db).mark_delivered([nid], uid)
        await db.commit()


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
        try:
            await _send_backlog(websocket, uid)
        except WebSocketDisconnect:
            raise
        except Exception:
            # DB 抖动等:补投失败不掐连接,实时推送仍可用;下次重连再补
            logger.exception("push backlog failed for user %s", uid)
        while True:
            # 客户端应用层心跳(NAT 保活)+ 送达回执;其余消息忽略。断开抛 WebSocketDisconnect。
            msg = await websocket.receive_json()
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg.get("type") == "ack":
                await _mark_acked(uid, msg.get("id"))
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
        logger.info("push ws closed: user=%s", uid)
