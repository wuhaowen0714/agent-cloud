from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.api.ownership import owned_session
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.models.user import User
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
from agent_cloud_backend.turn.headless import (
    HeadlessOverflow,
    HeadlessWorkerError,
    SessionBusy,
    execute_turn_headless,
)
from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub, get_turn_hub, subscribe
from agent_cloud_backend.turn.retry import classify
from agent_cloud_backend.turn.runner import run_turn

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
    user: User = Depends(get_current_user),
):
    # 薄包一层:鉴权 + 把回合执行委托给 execute_turn_headless(与定时任务轮询器共用)。
    # 异常映射保持原语义:并发 409 / 超窗压无可压 413 / 瞬时 503 / 其它 worker 502。
    await owned_session(session_id, user.id, db)  # 404 if missing or not owned
    try:
        result = await execute_turn_headless(
            session_id, body.content, settings=settings, manager=manager, store=store
        )
    except SessionBusy as exc:
        raise HTTPException(status_code=409, detail="session is busy") from exc
    except HeadlessOverflow as exc:
        raise HTTPException(
            status_code=413, detail="context too large to compact; please start a new session"
        ) from exc
    except HeadlessWorkerError as exc:
        if classify(exc.code) == "transient":
            raise HTTPException(
                status_code=503, detail="service unavailable, please retry"
            ) from exc
        raise HTTPException(status_code=502, detail=f"worker unavailable: {exc.code.name}") from exc
    return TurnResponse(
        messages=result.new_messages,
        stop_reason=result.stop_reason,
        usage=TurnUsage(input_tokens=result.input_tokens, output_tokens=result.output_tokens),
    )


@router.post("/stream")
async def stream_turn_endpoint(
    session_id: uuid.UUID,
    body: TurnRequest,
    settings: Settings = Depends(get_settings),
    manager: SandboxManager = Depends(get_sandbox_manager),
    store: ObjectStore = Depends(get_object_store),
    hub: TurnHub = Depends(get_turn_hub),
    user: User = Depends(get_current_user),
):
    # 用显式 DB session 做准备工作并在返回订阅流【之前】关闭:否则 Depends(get_session)
    # 的会话会被 FastAPI 持有到流结束,长回合白占一个请求 DB 连接。订阅流本身不碰 DB。
    async with get_sessionmaker()() as db:
        session_repo = SessionRepository(db)
        s = await owned_session(session_id, user.id, db)  # 404 if missing or not owned
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
                    content={
                        "text": body.content,
                        "images": body.images,
                        "tool_calls": [],
                        "tool_results": [],
                    },
                ),
            )
            await db.commit()
            sandbox_conn = await manager.get_endpoint_for_user(s.user_id)
            sandbox_endpoint = sandbox_conn.endpoint
            sandbox_token = sandbox_conn.token
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
                sandbox_token=sandbox_token,
                user_message=body.content,
                images=body.images,
                exclude_message_id=user_msg.id,
                enabled_skills=enabled_skills,
                work_subdir=req_work_subdir,
                client_platform=body.client,
            )
        except Exception:
            await db.rollback()
            await session_repo.release(session_id)
            await db.commit()
            raise

    # 重试时重新组装请求:开新 DB session(读到 force_compact 写回的新摘要),重查 skills
    # (避免跨已关闭 session 访问 ORM)。worker/可恢复失败时由 runner 调用。
    async def _reassemble():
        async with get_sessionmaker()() as rdb:
            rs = await SessionRepository(rdb).get(session_id)
            rskills = await AgentSkillEnableRepository(rdb).list_enabled_for_agent(
                rs.agent_config_id
            )
            return await build_run_turn_request(
                rdb,
                rs,
                sandbox_endpoint=sandbox_endpoint,
                sandbox_token=sandbox_token,
                user_message=body.content,
                images=body.images,
                exclude_message_id=user_msg.id,
                enabled_skills=rskills,
                work_subdir=req_work_subdir,
                client_platform=body.client,
            )

    # DB 已关闭。起独立 Runner(asyncio.create_task,断连不取消)+ 返回订阅流(补播+实时)。
    active = ActiveTurn(session_id=session_id)
    hub.register(active)
    active.task = asyncio.create_task(
        run_turn(
            hub,
            active,
            worker_endpoint=settings.worker_endpoint,
            request=request,
            reassemble=_reassemble,
            session_id=session_id,
            heartbeat_interval=settings.session_heartbeat_seconds,
            settings=settings,
            # 标题为空才在成功收尾后异步起名(钩子内还有权威复查)
            spawn_title=s.title is None,
        )
    )
    return StreamingResponse(subscribe(active), media_type="text/event-stream")


@router.get("/stream")
async def resume_turn_endpoint(
    session_id: uuid.UUID,
    hub: TurnHub = Depends(get_turn_hub),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """重连:该会话有进行中回合 → 补播已发事件 + 续看实时;没有 → 204。"""
    await owned_session(session_id, user.id, db)  # 404 if missing or not owned
    active = hub.get(session_id)
    if active is None:
        return Response(status_code=204)
    return StreamingResponse(subscribe(active), media_type="text/event-stream")


@router.post("/cancel", status_code=204)
async def cancel_turn_endpoint(
    session_id: uuid.UUID,
    hub: TurnHub = Depends(get_turn_hub),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """主动停止正在跑的回合(幂等:无在跑回合也 204)。"""
    await owned_session(session_id, user.id, db)  # 404 if missing or not owned
    active = hub.get(session_id)
    if active is not None and active.task is not None:
        active.task.cancel()
    return Response(status_code=204)
