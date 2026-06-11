import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.api.ownership import owned_agent, owned_session
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.schemas.session import (
    ForkRequest,
    ForkResult,
    RollbackRequest,
    RollbackResult,
    SessionCreate,
    SessionRead,
    SessionUpdate,
)
from agent_cloud_backend.turn.compaction import compact
from agent_cloud_backend.turn.heartbeat import session_heartbeat

logger = logging.getLogger(__name__)

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


@router.patch("/{session_id}", response_model=SessionRead)
async def rename_session(
    session_id: uuid.UUID,
    body: SessionUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    s = await owned_session(session_id, user.id, session)  # 404
    title = body.title.strip()
    if not title or len(title) > 200:
        raise HTTPException(status_code=422, detail="title must be 1-200 chars")
    s.title = title
    await session.commit()
    await session.refresh(s)
    return s


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    await owned_session(session_id, user.id, session)  # 404
    if not await SessionRepository(session).delete_if_idle(session_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="session busy")
    await session.commit()  # messages 由 FK CASCADE 连带删除


@router.post("/{session_id}/compact")
async def compact_session(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """手动压缩当前会话上下文。与回合用同一把会话锁:回合进行中 → 409。

    压缩期间用 session_heartbeat 续租(与回合端点一致):压缩可能串行打两次 worker
    (记忆提炼 + 摘要),不续租则长压缩会在 lease 过期后被并发回合抢锁,造成摘要/边界
    数据竞态,且收尾的 release 会把回合的锁一并抹成 idle。
    """
    await owned_session(session_id, user.id, session)  # 不属本人/不存在 → 404
    if not await SessionRepository(session).try_acquire(session_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="session busy")
    await session.commit()  # 持久化 running 锁(仅抢到时才写)
    try:
        async with session_heartbeat(session_id, settings.session_heartbeat_seconds):
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


async def _require_user_message(
    repo: MessageRepository, session_id: uuid.UUID, message_id: uuid.UUID
) -> tuple[int, str]:
    """取本会话内的某条 user 消息,返回 (seq, text);非本会话/非 user → 422。"""
    msg = await repo.get_in_session(session_id, message_id)
    if msg is None or msg.role != "user":
        raise HTTPException(
            status_code=422, detail="message must be a user message in this session"
        )
    return msg.seq, msg.content["text"]


@router.post("/{session_id}/rollback", response_model=RollbackResult)
async def rollback_session(
    session_id: uuid.UUID,
    body: RollbackRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """回到该用户消息「之前」:删 seq>=target 的全部消息 + 修压缩/记忆游标。回滚是销毁性写,
    与回合/压缩同一把会话锁:会话在跑 → 409。不动文件(工作区用户级共享,与会话历史无关)。"""
    await owned_session(session_id, user.id, session)  # 不属本人/不存在 → 404
    repo = MessageRepository(session)
    sess_repo = SessionRepository(session)
    target, user_text = await _require_user_message(repo, session_id, body.message_id)
    if not await sess_repo.try_acquire(session_id):
        await session.rollback()
        raise HTTPException(status_code=409, detail="session is busy")
    await session.commit()  # 持久化 running 锁(仅抢到时才写)
    try:
        deleted = await repo.delete_from_seq(session_id, target)
        await sess_repo.apply_rollback_cursors(session_id, target)
        await session.commit()
        return RollbackResult(deleted_count=deleted, user_text=user_text)
    finally:
        # 释放锁,对中途 DB 出错有韧性(参考 turn 端点):先 rollback 清事务,再 release+commit。
        try:
            await session.rollback()
            await sess_repo.release(session_id)
            await session.commit()
        except Exception:
            logger.exception("rollback: failed to release lock for session %s", session_id)


@router.post("/{session_id}/fork", response_model=ForkResult)
async def fork_session(
    session_id: uuid.UUID,
    body: ForkRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """从该用户消息「之前」复制出一个新会话(原会话原样保留)。只读原会话,允许其在跑。
    新会话同 agent / 同共享工作区;摘要仅当完全落在被复制区间内才带过去。"""
    s = await owned_session(session_id, user.id, session)  # 404
    repo = MessageRepository(session)
    target, user_text = await _require_user_message(repo, session_id, body.message_id)
    new = Session(
        user_id=s.user_id,
        agent_config_id=s.agent_config_id,
        work_subdir=s.work_subdir,
        title=(f"{s.title}(分支)" if s.title else None),
        summary=s.summary,
        summary_through_seq=s.summary_through_seq,
        memory_through_seq=s.memory_through_seq,
    )
    session.add(new)
    await session.flush()  # 拿 new.id
    max_copied = await repo.copy_prefix_to(session_id, new.id, target)
    # 按【实际复制到的最大 seq】钳游标,而非按 target——若读 s 之后、复制之前发生并发回滚把
    # 原会话删得更短,这里仍保证新会话游标不超出真实复制范围(否则新会话首条消息 seq 会落在
    # 陈旧游标之下、被组装/记忆漏掉,评审 I1)。摘要仅当完全落在已复制区间内才保留。
    if new.summary_through_seq > max_copied:
        new.summary = ""
        new.summary_through_seq = -1
    new.memory_through_seq = min(new.memory_through_seq, max_copied)
    await session.commit()
    return ForkResult(new_session_id=new.id, user_text=user_text)
