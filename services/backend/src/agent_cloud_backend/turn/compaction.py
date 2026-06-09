from __future__ import annotations

import logging
import uuid

from agent_cloud.v1 import worker_pb2
from agent_cloud_common.codec import msg_to_proto

from agent_cloud_backend.config import Settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.turn.credentials import resolve_agent_key
from agent_cloud_backend.turn.memory_extract import extract_session_memory
from agent_cloud_backend.turn.messages import orm_to_common, strip_unanswered_user_messages
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
    # 折叠前先提炼记忆(否则细节被摘要抹掉);best-effort,不因记忆失败坏掉压缩。
    try:
        await extract_session_memory(session_id, settings=settings, reason="compaction")
    except Exception:
        logger.exception("pre-compaction memory extract failed for session %s", session_id)
    async with get_sessionmaker()() as db:
        session = await SessionRepository(db).get(session_id)
        if session is None:
            return False
        agent = await AgentConfigRepository(db).get(session.agent_config_id)
        if agent is None:  # FK 是 RESTRICT,正常不可能;防御性,与 session 检查对齐
            return False
        history = await MessageRepository(db).list_by_session(session_id)
        history_after = [m for m in history if m.seq > session.summary_through_seq]
        folded = _fold_boundary(history_after, keep_recent)
        if folded is None:
            return False
        fold_msgs, boundary_seq = folded
        # boundary 用未清洗的 fold[-1].seq(已折叠位置都要推进,清洗掉的也不再回看);
        # 但发给 Summarizer 的内容与 assemble 发给模型的一致(去掉被取消回合的未答 user 消息)。
        fold_msgs = strip_unanswered_user_messages(fold_msgs)
        if not fold_msgs:
            # 折叠窗口里全是被取消回合的未答 user 消息:无内容可摘要,直接推进边界跳过它们。
            session.summary_through_seq = boundary_seq
            await db.commit()
            return True
        # BYO-Key:摘要也用本人凭据(无/不属本人 → 回退全局)。
        api_key, base_url = await resolve_agent_key(
            db, agent.key_ref or "", session.user_id, settings
        )
        req = worker_pb2.SummarizeRequest(
            agent=worker_pb2.Agent(
                model=agent.model,
                provider=agent.provider,
                key_ref=agent.key_ref or "",
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


async def maybe_compact_after_turn(
    session_id: uuid.UUID, context_tokens: int, *, model: str, settings: Settings
) -> None:
    """回合后主动压缩:用模型返回的真实 context_tokens 判阈值(阈值按模型解析,可 per-model
    覆盖)。best-effort——绝不因压缩失败坏掉已成功的回合。"""
    if context_tokens <= settings.compaction_threshold_for(model):
        return
    try:
        await compact(
            session_id,
            worker_endpoint=settings.worker_endpoint,
            keep_recent=settings.compaction_keep_recent,
            settings=settings,
        )
    except Exception:
        logger.exception("post-turn compaction failed for session %s", session_id)


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
