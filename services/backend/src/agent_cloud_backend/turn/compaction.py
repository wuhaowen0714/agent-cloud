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
from agent_cloud_backend.turn.messages import orm_to_common
from agent_cloud_backend.turn.worker_client import summarize_via_worker

logger = logging.getLogger(__name__)


def _fold_boundary(history_after: list, keep_recent: int):
    """保留最近 keep_recent 条,其余为待折叠。不足以折叠则 None。返回 (fold_msgs, boundary_seq)。"""
    if len(history_after) <= keep_recent:
        return None
    fold = history_after[:-keep_recent]
    return fold, fold[-1].seq


async def compact(session_id: uuid.UUID, *, worker_endpoint: str, keep_recent: int) -> bool:
    """把 summary_through_seq 之后、最近 keep_recent 条之前的历史折叠进 session.summary(增量)。"""
    async with get_sessionmaker()() as db:
        session = await SessionRepository(db).get(session_id)
        if session is None:
            return False
        agent = await AgentConfigRepository(db).get(session.agent_config_id)
        history = await MessageRepository(db).list_by_session(session_id)
        history_after = [m for m in history if m.seq > session.summary_through_seq]
        folded = _fold_boundary(history_after, keep_recent)
        if folded is None:
            return False
        fold_msgs, boundary_seq = folded
        req = worker_pb2.SummarizeRequest(
            agent=worker_pb2.Agent(
                model=agent.model, provider=agent.provider, key_ref=agent.key_ref or ""
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
    session_id: uuid.UUID, context_tokens: int, *, settings: Settings
) -> None:
    """回合后主动压缩:用模型返回的真实 context_tokens 判阈值。
    best-effort——绝不因压缩失败坏掉已成功的回合。"""
    if context_tokens <= settings.compaction_token_threshold:
        return
    try:
        await compact(
            session_id,
            worker_endpoint=settings.worker_endpoint,
            keep_recent=settings.compaction_keep_recent,
        )
    except Exception:
        logger.exception("post-turn compaction failed for session %s", session_id)


async def force_compact(session_id: uuid.UUID, *, settings: Settings) -> None:
    """撞 400 兜底:更激进(只留最近 2 条)。best-effort。"""
    try:
        await compact(session_id, worker_endpoint=settings.worker_endpoint, keep_recent=2)
    except Exception:
        logger.exception("force compaction failed for session %s", session_id)
