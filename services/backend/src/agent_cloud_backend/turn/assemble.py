from __future__ import annotations

import uuid

from agent_cloud.v1 import worker_pb2
from agent_cloud_common.codec import msg_to_proto
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.models.session import Session
from agent_cloud_backend.models.skill import Skill
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.context_document import ContextDocumentRepository
from agent_cloud_backend.repositories.memory_entry import MemoryEntryRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.skills.materialize import skill_location
from agent_cloud_backend.turn.messages import orm_to_common


def _strip_unanswered_user_messages(history: list) -> list:
    """丢弃没有助手回复的 user 消息——被取消/出错的回合只在库里留下了 user 消息
    (助手消息仅在 TurnDone 成功时才落库)。否则模型会把上一轮没答完的问题也一并
    回答。判定:某 user 消息之后紧跟的不是助手/工具消息(是另一个 user,或已到末尾)。"""
    kept = []
    for i, m in enumerate(history):
        if m.role == "user":
            nxt = history[i + 1] if i + 1 < len(history) else None
            if nxt is None or nxt.role == "user":
                continue
        kept.append(m)
    return kept


async def build_run_turn_request(
    db: AsyncSession,
    session: Session,
    *,
    sandbox_endpoint: str,
    user_message: str,
    exclude_message_id: uuid.UUID | None,
    enabled_skills: list[Skill] | None = None,
    work_subdir: str | None = None,
) -> worker_pb2.RunTurnRequest:
    agent = await AgentConfigRepository(db).get(session.agent_config_id)
    doc_repo = ContextDocumentRepository(db)
    user_docs = await doc_repo.list_for_owner("user", session.user_id)
    agent_docs = await doc_repo.list_for_owner("agent", session.agent_config_id)
    mem_repo = MemoryEntryRepository(db)
    user_mem = await mem_repo.list_for_context("user", session.user_id)
    agent_mem = await mem_repo.list_for_context("agent", session.agent_config_id)
    history = await MessageRepository(db).list_by_session(session.id)
    history = [m for m in history if m.id != exclude_message_id]
    history = _strip_unanswered_user_messages(history)

    return worker_pb2.RunTurnRequest(
        session_id=str(session.id),
        user_id=str(session.user_id),
        agent=worker_pb2.Agent(
            model=agent.model,
            provider=agent.provider,
            thinking_level=agent.thinking_level or "",
            enabled_tools=list(agent.enabled_tools),
            key_ref=agent.key_ref or "",
        ),
        documents=[
            worker_pb2.Doc(scope=d.scope, type=d.type, content=d.content)
            for d in [*user_docs, *agent_docs]
        ],
        memory=[worker_pb2.Mem(scope=e.scope, content=e.content) for e in [*user_mem, *agent_mem]],
        skills=[
            worker_pb2.Skill(
                name=sk.name, description=sk.description, location=skill_location(sk.name)
            )
            for sk in (enabled_skills or [])
        ],
        messages=[msg_to_proto(orm_to_common(m)) for m in history],
        user_message=user_message,
        sandbox_endpoint=sandbox_endpoint,
        work_subdir=work_subdir if work_subdir is not None else session.work_subdir,
    )
