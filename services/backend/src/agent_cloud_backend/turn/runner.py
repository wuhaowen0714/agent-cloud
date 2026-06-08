from __future__ import annotations

import asyncio
import logging
import uuid

import grpc
from agent_cloud_common import TurnDone
from agent_cloud_common.codec import turn_event_from_proto

from agent_cloud_backend.config import Settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.turn import worker_client
from agent_cloud_backend.turn.compaction import force_compact, maybe_compact_after_turn
from agent_cloud_backend.turn.heartbeat import session_heartbeat
from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
from agent_cloud_backend.turn.messages import common_to_content
from agent_cloud_backend.turn.sse import error_sse, turn_event_to_sse

logger = logging.getLogger(__name__)


async def _persist(session_id: uuid.UUID, new_messages) -> list[str]:
    ids: list[str] = []
    async with get_sessionmaker()() as db:
        repo = MessageRepository(db)
        for common in new_messages:
            row = await repo.append(
                session_id,
                Message(
                    session_id=session_id,
                    seq=0,
                    role=common.role.value,
                    content=common_to_content(common),
                ),
            )
            ids.append(str(row.id))
        await db.commit()
    return ids


async def _release_session_lock(session_id: uuid.UUID) -> None:
    try:
        async with get_sessionmaker()() as db:
            await SessionRepository(db).release(session_id)
            await db.commit()
    except Exception:
        logger.exception("failed to release session lock for session %s", session_id)


async def _finalize(active: ActiveTurn, session_id: uuid.UUID) -> None:
    """唤醒订阅者(done)+ 释放会话锁。包进 shield 调用,二次取消下仍跑完。"""
    await active.finish()
    await _release_session_lock(session_id)


async def drain_hub(hub: TurnHub) -> None:
    """关停时调用:取消所有 runner、等其收尾,再兜底释放仍在 hub 里(含从未启动
    就被取消、其 finally 未跑的)会话锁,避免锁卡到 600s 租约过期(I2/I3)。"""
    tasks = hub.all_tasks()
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    for sid in hub.session_ids():
        await _release_session_lock(sid)
        hub.remove(sid)


async def run_turn(
    hub: TurnHub,
    active: ActiveTurn,
    *,
    worker_endpoint: str,
    request,
    session_id: uuid.UUID,
    heartbeat_interval: float,
    settings: Settings,
) -> None:
    """独立任务:消费 worker 流 → 缓冲 + 落库;断连不取消它(由 asyncio.create_task 起)。"""
    ctx_tokens = 0
    try:
        async with session_heartbeat(session_id, heartbeat_interval):
            async for proto_event in worker_client.stream_turn_via_worker(worker_endpoint, request):
                event = turn_event_from_proto(proto_event)
                if isinstance(event, TurnDone):
                    message_ids = await _persist(session_id, event.new_messages)
                    ctx_tokens = event.context_tokens
                    await active.emit(
                        {
                            "type": "turn_done",
                            "usage": {
                                "input_tokens": event.usage.input_tokens,
                                "output_tokens": event.usage.output_tokens,
                            },
                            "message_ids": message_ids,
                            "stop_reason": event.stop_reason,
                        }
                    )
                else:
                    await active.emit(turn_event_to_sse(event))
        # 回合成功收尾后主动压缩(用模型返回的真实 context_tokens 判阈值)。
        # best-effort(内部吞异常),且仍在会话锁内(_finalize 释放锁在 finally,晚于此)。
        await maybe_compact_after_turn(session_id, ctx_tokens, settings=settings)
    except asyncio.CancelledError:
        # 主动取消 → 转成干净的终止事件,让 finally 收尾(不再 re-raise)
        await active.emit({"type": "error", "message": "turn cancelled", "recoverable": False})
    except grpc.aio.AioRpcError as exc:
        # 上下文超窗(worker → RESOURCE_EXHAUSTED):兜底 force-compact 后,作为可恢复错误
        # 提示重试(error_sse 已把 RESOURCE_EXHAUSTED 归为 recoverable)。仍在锁内。
        if exc.code() == grpc.StatusCode.RESOURCE_EXHAUSTED:
            await force_compact(session_id, settings=settings)
        await active.emit(error_sse(exc.code()))
    except Exception:
        logger.exception("turn run failed for session %s", session_id)
        await active.emit({"type": "error", "message": "the turn failed", "recoverable": False})
    finally:
        # 进入 finally 后,务必在后续(二次)取消下仍完成:从 Hub 移除 + 唤醒订阅者 +
        # 释放锁。hub.remove 同步先做(无 await,必成);finish+release 包进 shield 的
        # 一个协程,二次取消时其内部仍跑完(C1)。
        hub.remove(session_id)
        await asyncio.shield(_finalize(active, session_id))
