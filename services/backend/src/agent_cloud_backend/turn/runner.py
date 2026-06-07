from __future__ import annotations

import asyncio
import logging
import uuid

import grpc
from agent_cloud_common import TurnDone
from agent_cloud_common.codec import turn_event_from_proto

from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.turn import worker_client
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


async def run_turn(
    hub: TurnHub,
    active: ActiveTurn,
    *,
    worker_endpoint: str,
    request,
    session_id: uuid.UUID,
    heartbeat_interval: float,
) -> None:
    """独立任务:消费 worker 流 → 缓冲 + 落库;断连不取消它(由 asyncio.create_task 起)。"""
    try:
        async with session_heartbeat(session_id, heartbeat_interval):
            async for proto_event in worker_client.stream_turn_via_worker(worker_endpoint, request):
                event = turn_event_from_proto(proto_event)
                if isinstance(event, TurnDone):
                    message_ids = await _persist(session_id, event.new_messages)
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
    except asyncio.CancelledError:
        # 主动取消 → 转成干净的终止事件,让 finally 收尾(不再 re-raise)
        await active.emit({"type": "error", "message": "turn cancelled", "recoverable": False})
    except grpc.aio.AioRpcError as exc:
        await active.emit(error_sse(exc.code()))
    except Exception:
        logger.exception("turn run failed for session %s", session_id)
        await active.emit({"type": "error", "message": "the turn failed", "recoverable": False})
    finally:
        await active.finish()
        await asyncio.shield(_release_session_lock(session_id))
        hub.remove(session_id)
