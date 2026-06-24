from __future__ import annotations

import uuid

from agent_cloud.v1 import worker_pb2
from agent_cloud_common.codec import msg_to_proto
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.config import get_settings
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.models.skill import Skill
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.context_document import ContextDocumentRepository
from agent_cloud_backend.repositories.memory_entry import MemoryEntryRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.skills.materialize import skill_location
from agent_cloud_backend.turn.credentials import resolve_session_key
from agent_cloud_backend.turn.messages import (
    active_images,
    is_subagent_orm,
    orm_to_common,
    strip_unanswered_user_messages,
)


async def build_run_turn_request(
    db: AsyncSession,
    session: Session,
    *,
    sandbox_endpoint: str,
    user_message: str,
    exclude_message_id: uuid.UUID | None,
    enabled_skills: list[Skill] | None = None,
    work_subdir: str | None = None,
    sandbox_token: str = "",
    is_scheduled_run: bool = False,
    images: list[str] | None = None,
) -> worker_pb2.RunTurnRequest:
    agent = await AgentConfigRepository(db).get(session.agent_config_id)
    doc_repo = ContextDocumentRepository(db)
    user_docs = await doc_repo.list_for_owner("user", session.user_id)
    agent_docs = await doc_repo.list_for_owner("agent", session.agent_config_id)
    mem_repo = MemoryEntryRepository(db)
    # 注入"当前块"(每作用域 version 最大的一条),不再是最近 N 条(spec 2026-06-09)。
    mem_blocks = [
        b
        for b in (
            await mem_repo.get_current("user", session.user_id),
            await mem_repo.get_current("agent", session.agent_config_id),
        )
        if b is not None and b.content.strip()
    ]
    history = await MessageRepository(db).list_by_session(session.id)
    # 压缩后:已折叠进 summary 的消息(seq <= summary_through_seq)不再逐字发,
    # 改由 history_summary 承载;未压缩会话的 summary_through_seq=-1,等价于不过滤。
    history = [
        m
        for m in history
        if m.id != exclude_message_id
        and m.seq > session.summary_through_seq
        and not is_subagent_orm(m)  # 子 agent 中间过程绝不喂回主 agent(只服务前端历史重建)
    ]
    history = strip_unanswered_user_messages(history)

    # BYO-Key:按 session.credential_id 取本人凭据解密;None/不属本人 → ("",""),worker 回退平台。
    api_key, base_url = await resolve_session_key(
        db, session.credential_id, session.user_id, get_settings()
    )

    return worker_pb2.RunTurnRequest(
        session_id=str(session.id),
        user_id=str(session.user_id),
        agent=worker_pb2.Agent(
            model=session.model,
            provider=("sophnet" if session.credential_id is None else "custom"),
            enabled_tools=list(agent.enabled_tools),
            api_key=api_key,
            base_url=base_url,
        ),
        documents=[
            worker_pb2.Doc(scope=d.scope, type=d.type, content=d.content)
            for d in [*user_docs, *agent_docs]
            if d.content.strip()  # 跳过空文档(如被清空的 AGENTS),不往 prompt 里塞空段
        ],
        memory=[worker_pb2.Mem(scope=b.scope, content=b.content) for b in mem_blocks],
        skills=[
            worker_pb2.Skill(
                name=sk.name, description=sk.description, location=skill_location(sk.name)
            )
            for sk in (enabled_skills or [])
        ],
        messages=[msg_to_proto(orm_to_common(m)) for m in history],
        user_message=user_message,
        turn_images=active_images(history, images or []),
        sandbox_endpoint=sandbox_endpoint,
        work_subdir=work_subdir if work_subdir is not None else session.work_subdir,
        history_summary=session.summary,
        sandbox_token=sandbox_token,
        is_scheduled_run=is_scheduled_run,
    )
