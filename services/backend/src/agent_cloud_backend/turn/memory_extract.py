from __future__ import annotations

import logging
import uuid

from agent_cloud.v1 import worker_pb2
from agent_cloud_common.codec import msg_to_proto
from sqlalchemy import func, select

from agent_cloud_backend.config import Settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.memory_entry import MemoryConflict, MemoryEntryRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.turn.credentials import resolve_agent_key
from agent_cloud_backend.turn.messages import orm_to_common
from agent_cloud_backend.turn.worker_client import extract_memory_via_worker

logger = logging.getLogger(__name__)


def _rounds(msgs: list) -> int:
    """对话轮次 = 用户消息条数。"""
    return sum(1 for m in msgs if m.role == "user")


async def extract_session_memory(
    session_id: uuid.UUID, *, settings: Settings, reason: str
) -> bool:
    """从某会话自上次水位线以来的新消息提炼记忆,更新 user 块(spec 2026-06-09)。

    reason='idle' 受 memory_min_rounds 轮次闸约束;reason='compaction' 不设闸(折叠前必提)。
    返回是否写入了新版本。best-effort:并发冲突则放弃本次(下次再提)。
    """
    async with get_sessionmaker()() as db:
        s = await db.get(Session, session_id)
        if s is None:
            return False
        msgs = [
            m
            for m in await MessageRepository(db).list_by_session(s.id)
            if m.seq > s.memory_through_seq
        ]
        if not msgs:
            return False
        if reason == "idle" and _rounds(msgs) < settings.memory_min_rounds:
            return False  # 轮次闸:只聊一两句就空闲的不值得花一次 LLM

        agent = await AgentConfigRepository(db).get(s.agent_config_id)
        if agent is None:
            return False
        # BYO-Key:用本人凭据(无/不属本人 → ("","") 回退全局)。key 仅经 worker。
        api_key, base_url = await resolve_agent_key(db, agent.key_ref or "", s.user_id, settings)
        mem_repo = MemoryEntryRepository(db)
        cur = await mem_repo.get_current("user", s.user_id)
        req = worker_pb2.ExtractMemoryRequest(
            agent=worker_pb2.Agent(
                model=agent.model,
                provider=agent.provider,
                key_ref=agent.key_ref or "",
                api_key=api_key,
                base_url=base_url,
            ),
            user_memory=cur.content if cur else "",
            agent_memory="",  # v1 不自动提 agent 层
            messages=[msg_to_proto(orm_to_common(m)) for m in msgs],
            soft_max_chars=settings.memory_soft_chars,
        )
        resp = await extract_memory_via_worker(settings.worker_endpoint, req)

        max_seq = max(m.seq for m in msgs)
        wrote = False
        if resp.user_changed:
            expected = cur.version if cur else 0
            try:
                await mem_repo.write_version(
                    "user", s.user_id, resp.user_memory, s.id, expected_version=expected
                )
                await mem_repo.prune("user", s.user_id, settings.memory_max_versions)
                wrote = True
            except MemoryConflict:
                # 并发赢家已写该版本;放弃本次(不推进水位线,下次再提)。
                logger.info("memory write conflict for user %s; skipping this pass", s.user_id)
                return False
        s.memory_through_seq = max_seq  # 不论写没写都推进,避免反复重提同一批
        await db.commit()
        return wrote


async def _idle_session_ids(db, idle_seconds: int) -> list[uuid.UUID]:
    """空闲够久(非 running、last_active_at 早于 cutoff)且有未提炼新消息的会话。"""
    cutoff = func.now() - func.make_interval(0, 0, 0, 0, 0, 0, idle_seconds)
    has_new = (
        select(Message.id)
        .where(Message.session_id == Session.id, Message.seq > Session.memory_through_seq)
        .exists()
    )
    rows = await db.execute(
        select(Session.id).where(
            Session.status != "running",
            Session.last_active_at < cutoff,
            has_new,
        )
    )
    return list(rows.scalars().all())


async def scan_idle_and_extract(settings: Settings) -> int:
    """reaper 周期调用:对空闲且攒够新对话的会话各提炼一次(轮次闸在 extract 内生效)。"""
    async with get_sessionmaker()() as db:
        ids = await _idle_session_ids(db, settings.memory_idle_seconds)
    n = 0
    for sid in ids:
        try:
            if await extract_session_memory(sid, settings=settings, reason="idle"):
                n += 1
        except Exception:
            logger.exception("idle memory extract failed for session %s", sid)
    return n
