from __future__ import annotations

import asyncio
import logging
import uuid

import grpc
from agent_cloud_common import TurnDone
from agent_cloud_common.codec import msg_from_proto, turn_event_from_proto
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.schemas.turn import TurnRequest, TurnResponse, TurnUsage
from agent_cloud_backend.turn.assemble import build_run_turn_request
from agent_cloud_backend.turn.messages import common_to_content
from agent_cloud_backend.turn.sse import error_sse, format_sse, turn_event_to_sse
from agent_cloud_backend.turn.worker_client import (
    run_turn_via_worker,
    stream_turn_via_worker,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions/{session_id}/turn", tags=["turn"])


@router.post("", response_model=TurnResponse)
async def run_turn_endpoint(
    session_id: uuid.UUID,
    body: TurnRequest,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    session_repo = SessionRepository(db)
    msg_repo = MessageRepository(db)

    s = await session_repo.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")

    # 1. 加锁(失败=并发,拒绝;不落任何东西)
    if not await session_repo.try_acquire(session_id):
        await db.rollback()
        raise HTTPException(status_code=409, detail="session is busy")
    await db.commit()

    try:
        # 2. 持久化 user 消息
        user_msg = await msg_repo.append(
            session_id,
            Message(
                session_id=session_id,
                seq=0,
                role="user",
                content={"text": body.content, "tool_calls": [], "tool_results": []},
            ),
        )
        await db.commit()

        # 3. 组装 + 调 worker
        request = await build_run_turn_request(
            db,
            s,
            sandbox_endpoint=settings.sandbox_endpoint,
            user_message=body.content,
            exclude_message_id=user_msg.id,
        )
        try:
            response = await run_turn_via_worker(settings.worker_endpoint, request)
        except grpc.aio.AioRpcError as exc:
            raise HTTPException(
                status_code=502, detail=f"worker unavailable: {exc.code().name}"
            ) from exc

        # 4. 落库新消息
        persisted = []
        for proto_msg in response.new_messages:
            common = msg_from_proto(proto_msg)
            row = await msg_repo.append(
                session_id,
                Message(
                    session_id=session_id,
                    seq=0,
                    role=common.role.value,
                    content=common_to_content(common),
                ),
            )
            persisted.append(row)
        await db.commit()

        return TurnResponse(
            messages=persisted,
            stop_reason=response.stop_reason,
            usage=TurnUsage(
                input_tokens=response.input_tokens, output_tokens=response.output_tokens
            ),
        )
    finally:
        # 5. 释放锁(对中途 DB 出错具有韧性)
        # 若加锁与最终 commit 之间任何 DB 操作中止了事务,先 rollback 清理,
        # 再 release,最后 commit。整段加 try/except,避免释放锁的失败掩盖原始异常,
        # 同时保证锁不会永远卡在 running。成功路径上 rollback 是无害的 no-op。
        try:
            await db.rollback()
            await session_repo.release(session_id)
            await db.commit()
        except Exception:
            logger.exception("failed to release session lock for session %s", session_id)


async def _release_session_lock(session_id: uuid.UUID) -> None:
    """Open a fresh DB session, release the session lock, and commit.

    Runs as a standalone coroutine so it can be ``asyncio.shield``-ed by the
    caller: on a client disconnect the streaming generator is cancelled at its
    ``yield`` and the surrounding scope is torn down, but the lock release must
    still complete or the session would stay ``running`` until the lease (600s)
    expires. Any failure is swallowed-with-log so it never masks the original
    cancellation/exception and never strands the lock silently.
    """
    try:
        async with get_sessionmaker()() as db:
            await SessionRepository(db).release(session_id)
            await db.commit()
    except Exception:
        logger.exception("failed to release session lock for session %s", session_id)


async def _sse_stream(worker_endpoint: str, request, session_id: uuid.UUID):
    try:
        async for proto_event in stream_turn_via_worker(worker_endpoint, request):
            event = turn_event_from_proto(proto_event)
            if isinstance(event, TurnDone):
                message_ids = []
                async with get_sessionmaker()() as db:
                    msg_repo = MessageRepository(db)
                    for common in event.new_messages:
                        row = await msg_repo.append(
                            session_id,
                            Message(
                                session_id=session_id,
                                seq=0,
                                role=common.role.value,
                                content=common_to_content(common),
                            ),
                        )
                        message_ids.append(str(row.id))
                    await db.commit()
                yield format_sse(
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
                yield format_sse(turn_event_to_sse(event))
    except grpc.aio.AioRpcError as exc:
        yield format_sse(error_sse(exc.code()))
    except Exception:
        # Non-gRPC failures (e.g. a turn_done persist error, event decode, or
        # SSE mapping) would otherwise truncate the 200 stream silently. Emit a
        # terminal error event so the client knows the turn failed.
        # CancelledError is a BaseException, not Exception, so a client
        # disconnect is NOT swallowed here and still unwinds to the finally.
        logger.exception("turn stream failed")
        yield format_sse({"type": "error", "message": "the turn failed", "recoverable": False})
    finally:
        # Shield the WHOLE fresh-session + release + commit unit so it completes
        # even when this generator's scope is being cancelled (client
        # disconnect). Shielding only the inner SQL would not be enough: the
        # connection is torn down with the cancelled scope.
        await asyncio.shield(_release_session_lock(session_id))


@router.post("/stream")
async def stream_turn_endpoint(
    session_id: uuid.UUID,
    body: TurnRequest,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    session_repo = SessionRepository(db)
    s = await session_repo.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    if not await session_repo.try_acquire(session_id):
        await db.rollback()
        raise HTTPException(status_code=409, detail="session is busy")
    await db.commit()
    try:
        user_msg = await MessageRepository(db).append(
            session_id,
            Message(
                session_id=session_id,
                seq=0,
                role="user",
                content={"text": body.content, "tool_calls": [], "tool_results": []},
            ),
        )
        await db.commit()
        request = await build_run_turn_request(
            db,
            s,
            sandbox_endpoint=settings.sandbox_endpoint,
            user_message=body.content,
            exclude_message_id=user_msg.id,
        )
    except Exception:
        await db.rollback()
        await session_repo.release(session_id)
        await db.commit()
        raise
    return StreamingResponse(
        _sse_stream(settings.worker_endpoint, request, session_id),
        media_type="text/event-stream",
    )
