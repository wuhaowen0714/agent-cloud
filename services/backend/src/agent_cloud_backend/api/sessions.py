import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.api.ownership import owned_agent, owned_session
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.schemas.session import SessionCreate, SessionRead
from agent_cloud_backend.turn.compaction import compact

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: SessionCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    await owned_agent(body.agent_config_id, user.id, session)  # agent 须属本人,否则 404
    s = await SessionRepository(session).create_for(user.id, body.agent_config_id, body.title)
    await session.commit()
    return s


@router.get("", response_model=list[SessionRead])
async def list_sessions(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    return await SessionRepository(session).list_by_user(user.id)


@router.post("/{session_id}/compact")
async def compact_session(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """手动压缩当前会话上下文。与回合用同一把会话锁:回合进行中 → 409。"""
    await owned_session(session_id, user.id, session)  # 不属本人/不存在 → 404
    acquired = await SessionRepository(session).try_acquire(session_id)
    await session.commit()
    if not acquired:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="session busy")
    try:
        progressed = await compact(
            session_id,
            worker_endpoint=settings.worker_endpoint,
            keep_recent=settings.compaction_keep_recent,
            settings=settings,
        )
    finally:
        # 独立事务释放锁:绝不被上面的压缩成败影响。
        async with get_sessionmaker()() as db:
            await SessionRepository(db).release(session_id)
            await db.commit()
    return {"compacted": progressed}
