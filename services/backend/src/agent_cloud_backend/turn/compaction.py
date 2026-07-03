from __future__ import annotations

import logging
import uuid

from agent_cloud.v1 import worker_pb2
from agent_cloud_common.codec import msg_to_proto

from agent_cloud_backend.config import Settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.turn.credentials import resolve_session_key
from agent_cloud_backend.turn.memory_extract import extract_session_memory
from agent_cloud_backend.turn.messages import (
    is_subagent_orm,
    orm_to_common,
    strip_unanswered_user_messages,
)
from agent_cloud_backend.turn.worker_client import summarize_via_worker

logger = logging.getLogger(__name__)


def _fold_boundary(history_after: list, keep_recent: int):
    """保留最近 keep_recent 条,其余为待折叠。不足以折叠则 None。返回 (fold_msgs, boundary_seq)。"""
    if len(history_after) <= keep_recent:
        return None
    fold = history_after[:-keep_recent]
    return fold, fold[-1].seq


async def compact(
    session_id: uuid.UUID, *, worker_endpoint: str, keep_recent: int, settings: Settings
) -> bool:
    """把 summary_through_seq 之后、最近 keep_recent 条之前的历史折叠进 session.summary(增量)。"""
    async with get_sessionmaker()() as db:
        session = await SessionRepository(db).get(session_id)
        if session is None:
            return False
        history = await MessageRepository(db).list_by_session(session_id)
        # 子 agent 中间消息不进摘要(只服务前端历史重建);其 seq 在回合末尾,随后续回合压缩自然越过。
        history = [m for m in history if not is_subagent_orm(m)]
        history_after = [m for m in history if m.seq > session.summary_through_seq]
        folded = _fold_boundary(history_after, keep_recent)
        if folded is None:
            return False
        # 确认有可折叠内容后才提炼记忆(否则细节被摘要抹掉);放在 fold 判断之后——无可折叠时
        # 直接返回,不白跑一次记忆 LLM 调用(审查中低危 1 修法③)。best-effort,失败不坏压缩。
        try:
            await extract_session_memory(session_id, settings=settings, reason="compaction")
        except Exception:
            logger.exception("pre-compaction memory extract failed for session %s", session_id)
        fold_msgs, boundary_seq = folded
        # boundary 用未清洗的 fold[-1].seq(已折叠位置都要推进,清洗掉的也不再回看);
        # 但发给 Summarizer 的内容与 assemble 发给模型的一致(去掉被取消回合的未答 user 消息)。
        fold_msgs = strip_unanswered_user_messages(fold_msgs)
        if not fold_msgs:
            # 折叠窗口里全是被取消回合的未答 user 消息:无内容可摘要,直接推进边界跳过它们。
            session.summary_through_seq = boundary_seq
            await db.commit()
            return True
        # BYO-Key:摘要也用本人凭据(None/不属本人 → 回退平台)。
        api_key, base_url = await resolve_session_key(
            db, session.credential_id, session.user_id, settings
        )
        req = worker_pb2.SummarizeRequest(
            agent=worker_pb2.Agent(
                model=session.model,
                provider=("sophnet" if session.credential_id is None else "custom"),
                api_key=api_key,
                base_url=base_url,
            ),
            prior_summary=session.summary,
            messages=[msg_to_proto(orm_to_common(m)) for m in fold_msgs],
        )
        new_summary = await summarize_via_worker(worker_endpoint, req)
        session.summary = new_summary
        session.summary_through_seq = boundary_seq
        await db.commit()
        return True


async def compaction_due(session_id: uuid.UUID, *, settings: Settings) -> bool:
    """是否该在回合开始前压缩:上一回合落库的 last_context_tokens 超该模型阈值,**且**确有
    可折叠内容(可折叠条数 > keep_recent,与 compact 的 _fold_boundary 同口径)。后者防
    「少数几条巨型消息撑爆 token 但条数不足折叠」时每回合白 emit compacting + 白进 compact
    (审查中低危 1 修法①)。未超阈值时只做一次 session 轻读即返回;rollback 会清
    last_context_tokens(避免按已删历史误判),None 视为不超。"""
    async with get_sessionmaker()() as db:
        session = await SessionRepository(db).get(session_id)
        if session is None or session.last_context_tokens is None:
            return False
        if session.last_context_tokens <= settings.compaction_threshold_for(session.model):
            return False
        history = await MessageRepository(db).list_by_session(session_id)
        history = [m for m in history if not is_subagent_orm(m)]
        after = [m for m in history if m.seq > session.summary_through_seq]
    return len(after) > settings.compaction_keep_recent


async def maybe_compact_before_turn(session_id: uuid.UUID, *, settings: Settings) -> bool:
    """回合开始前主动压缩(P0):压缩发生在新回合锁的自然生命周期内——此前挂在 turn_done
    之后,前端已解锁输入而后端仍持锁压缩(两次串行 LLM 调用),用户紧接着发消息必撞 409。
    依据是上一回合落库的真实 context_tokens。best-effort——绝不因压缩失败坏掉回合。
    返回是否有折叠(调用方据此重组装请求,拿到新摘要)。"""
    try:
        if not await compaction_due(session_id, settings=settings):
            return False
        return await compact(
            session_id,
            worker_endpoint=settings.worker_endpoint,
            keep_recent=settings.compaction_keep_recent,
            settings=settings,
        )
    except Exception:
        logger.exception("pre-turn compaction failed for session %s", session_id)
        return False


async def force_compact(session_id: uuid.UUID, *, settings: Settings) -> bool:
    """撞 400 兜底:最大化折叠(只留最近 1 条)。best-effort。

    返回是否取得进展(True=折叠了内容/推进了边界)。无进展(已无可折叠 —— 仅剩最近一条
    + 摘要仍超窗)时返回 False,调用方据此把错误改判为**不可恢复**,避免用户陷入永久重试。"""
    try:
        return await compact(
            session_id, worker_endpoint=settings.worker_endpoint, keep_recent=1, settings=settings
        )
    except Exception:
        logger.exception("force compaction failed for session %s", session_id)
        return False
