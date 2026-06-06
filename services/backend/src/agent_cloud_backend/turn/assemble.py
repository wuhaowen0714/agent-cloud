from __future__ import annotations

import uuid

from agent_cloud.v1 import worker_pb2
from agent_cloud_common.codec import msg_to_proto
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.models.session import Session
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.context_document import ContextDocumentRepository
from agent_cloud_backend.repositories.memory_entry import MemoryEntryRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.turn.messages import orm_to_common


async def build_run_turn_request(
    db: AsyncSession,
    session: Session,
    *,
    sandbox_endpoint: str,
    user_message: str,
    exclude_message_id: uuid.UUID | None,
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
        skills=[],  # Plan 5
        messages=[msg_to_proto(orm_to_common(m)) for m in history],
        user_message=user_message,
        sandbox_endpoint=sandbox_endpoint,
        work_subdir=session.work_subdir,
    )
