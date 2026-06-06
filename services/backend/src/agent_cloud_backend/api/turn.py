from __future__ import annotations

import uuid

import grpc
from agent_cloud_common.codec import msg_from_proto
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.schemas.turn import TurnRequest, TurnResponse, TurnUsage
from agent_cloud_backend.turn.assemble import build_run_turn_request
from agent_cloud_backend.turn.messages import common_to_content
from agent_cloud_backend.turn.worker_client import run_turn_via_worker

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
        # 5. 释放锁
        await session_repo.release(session_id)
        await db.commit()
