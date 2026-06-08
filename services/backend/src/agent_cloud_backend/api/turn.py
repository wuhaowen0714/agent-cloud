from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

import grpc
from agent_cloud_common.codec import msg_from_proto
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.repositories.skill import AgentSkillEnableRepository
from agent_cloud_backend.sandbox.deps import get_sandbox_manager
from agent_cloud_backend.sandbox.manager import SandboxManager
from agent_cloud_backend.schemas.turn import TurnRequest, TurnResponse, TurnUsage
from agent_cloud_backend.skills.deps import get_object_store
from agent_cloud_backend.skills.materialize import materialize_enabled_skills
from agent_cloud_backend.skills.store import ObjectStore
from agent_cloud_backend.turn.assemble import build_run_turn_request
from agent_cloud_backend.turn.compaction import force_compact, maybe_compact_after_turn
from agent_cloud_backend.turn.heartbeat import session_heartbeat
from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub, get_turn_hub, subscribe
from agent_cloud_backend.turn.messages import common_to_content
from agent_cloud_backend.turn.runner import run_turn
from agent_cloud_backend.turn.worker_client import run_turn_via_worker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions/{session_id}/turn", tags=["turn"])


@router.post("", response_model=TurnResponse)
async def run_turn_endpoint(
    session_id: uuid.UUID,
    body: TurnRequest,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    manager: SandboxManager = Depends(get_sandbox_manager),
    store: ObjectStore = Depends(get_object_store),
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

        # 3. 组装 + 物化已启用 skill + 调 worker
        sandbox_endpoint = await manager.get_endpoint_for_user(s.user_id)
        enabled_skills = await AgentSkillEnableRepository(db).list_enabled_for_agent(
            s.agent_config_id
        )
        materialize_enabled_skills(
            base_root=Path(settings.sandbox_base_root),
            user_id=s.user_id,
            work_subdir=s.work_subdir,
            skills=enabled_skills,
            store=store,
        )
        # docker 沙箱:容器已把用户 workspace 挂到 /workspace,请求 work_subdir 用 "."
        # 避免再嵌套一层 workspace(spec §5);inprocess 仍用 session.work_subdir。
        # 注意:上面 materialize 仍用 s.work_subdir(那是宿主侧 .skills 路径)。
        req_work_subdir = "." if settings.sandbox_provisioner == "docker" else s.work_subdir
        request = await build_run_turn_request(
            db,
            s,
            sandbox_endpoint=sandbox_endpoint,
            user_message=body.content,
            exclude_message_id=user_msg.id,
            enabled_skills=enabled_skills,
            work_subdir=req_work_subdir,
        )
        try:
            async with session_heartbeat(session_id, settings.session_heartbeat_seconds):
                response = await run_turn_via_worker(settings.worker_endpoint, request)
        except grpc.aio.AioRpcError as exc:
            if exc.code() == grpc.StatusCode.RESOURCE_EXHAUSTED:
                # 上下文超窗:兜底 force-compact 后,返回可重试信号(503),让前端重发即可。
                await force_compact(session_id, settings=settings)
                raise HTTPException(
                    status_code=503, detail="context exceeded, compacted — please retry"
                ) from exc
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

        # 回合后主动压缩(用真实 context_tokens 判阈值)。best-effort,仍在会话锁内。
        await maybe_compact_after_turn(session_id, response.context_tokens, settings=settings)

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


@router.post("/stream")
async def stream_turn_endpoint(
    session_id: uuid.UUID,
    body: TurnRequest,
    settings: Settings = Depends(get_settings),
    manager: SandboxManager = Depends(get_sandbox_manager),
    store: ObjectStore = Depends(get_object_store),
    hub: TurnHub = Depends(get_turn_hub),
):
    # 用显式 DB session 做准备工作并在返回订阅流【之前】关闭:否则 Depends(get_session)
    # 的会话会被 FastAPI 持有到流结束,长回合白占一个请求 DB 连接。订阅流本身不碰 DB。
    async with get_sessionmaker()() as db:
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
            sandbox_endpoint = await manager.get_endpoint_for_user(s.user_id)
            enabled_skills = await AgentSkillEnableRepository(db).list_enabled_for_agent(
                s.agent_config_id
            )
            materialize_enabled_skills(
                base_root=Path(settings.sandbox_base_root),
                user_id=s.user_id,
                work_subdir=s.work_subdir,
                skills=enabled_skills,
                store=store,
            )
            req_work_subdir = "." if settings.sandbox_provisioner == "docker" else s.work_subdir
            request = await build_run_turn_request(
                db,
                s,
                sandbox_endpoint=sandbox_endpoint,
                user_message=body.content,
                exclude_message_id=user_msg.id,
                enabled_skills=enabled_skills,
                work_subdir=req_work_subdir,
            )
        except Exception:
            await db.rollback()
            await session_repo.release(session_id)
            await db.commit()
            raise

    # DB 已关闭。起独立 Runner(asyncio.create_task,断连不取消)+ 返回订阅流(补播+实时)。
    active = ActiveTurn(session_id=session_id)
    hub.register(active)
    active.task = asyncio.create_task(
        run_turn(
            hub,
            active,
            worker_endpoint=settings.worker_endpoint,
            request=request,
            session_id=session_id,
            heartbeat_interval=settings.session_heartbeat_seconds,
            settings=settings,
        )
    )
    return StreamingResponse(subscribe(active), media_type="text/event-stream")


@router.get("/stream")
async def resume_turn_endpoint(
    session_id: uuid.UUID,
    hub: TurnHub = Depends(get_turn_hub),
):
    """重连:该会话有进行中回合 → 补播已发事件 + 续看实时;没有 → 204。"""
    active = hub.get(session_id)
    if active is None:
        return Response(status_code=204)
    return StreamingResponse(subscribe(active), media_type="text/event-stream")


@router.post("/cancel", status_code=204)
async def cancel_turn_endpoint(
    session_id: uuid.UUID,
    hub: TurnHub = Depends(get_turn_hub),
):
    """主动停止正在跑的回合(幂等:无在跑回合也 204)。"""
    active = hub.get(session_id)
    if active is not None and active.task is not None:
        active.task.cancel()
    return Response(status_code=204)
