from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

import grpc
from agent_cloud_common.codec import msg_from_proto

from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.repositories.skill import AgentSkillEnableRepository
from agent_cloud_backend.skills.materialize import materialize_enabled_skills
from agent_cloud_backend.turn.assemble import build_run_turn_request
from agent_cloud_backend.turn.compaction import force_compact, maybe_compact_before_turn
from agent_cloud_backend.turn.heartbeat import session_heartbeat
from agent_cloud_backend.turn.messages import common_to_content
from agent_cloud_backend.turn.post_persist import run_tool_side_effects
from agent_cloud_backend.turn.retry import RetryAction, RetryPolicy, classify
from agent_cloud_backend.turn.title import spawn_title_generation
from agent_cloud_backend.turn.worker_client import run_turn_via_worker

logger = logging.getLogger(__name__)


class SessionBusy(Exception):
    """try_acquire 失败:会话被并发回合占用。"""


class HeadlessOverflow(Exception):
    """上下文压无可压(多轮压缩仍超窗)。"""


class HeadlessWorkerError(Exception):
    def __init__(self, code) -> None:
        self.code = code


@dataclass
class HeadlessResult:
    new_messages: list[Message]
    final_text: str
    stop_reason: str
    input_tokens: int
    output_tokens: int


async def execute_turn_headless(
    session_id: uuid.UUID, user_content: str, *, settings, manager, store, is_scheduled_run=False
) -> HeadlessResult:
    """无头执行一回合:加锁→落用户消息→组装→worker(带重试/压缩)→落 new_messages + remember
    副作用→回合后压缩→起名→释放锁。HTTP 非流式端点与定时任务轮询器共用。内部自管 DB session。
    try_acquire 失败抛 SessionBusy;超窗压无可压抛 HeadlessOverflow;worker 不可恢复
    抛 HeadlessWorkerError。
    """
    async with get_sessionmaker()() as db:
        if not await SessionRepository(db).try_acquire(session_id):
            await db.rollback()
            raise SessionBusy()
        await db.commit()
    try:
        async with get_sessionmaker()() as db:
            user_msg = await MessageRepository(db).append(
                session_id,
                Message(
                    session_id=session_id,
                    seq=0,
                    role="user",
                    content={"text": user_content, "tool_calls": [], "tool_results": []},
                ),
            )
            await db.commit()
            user_msg_id = user_msg.id

        async def _assemble():
            async with get_sessionmaker()() as db:
                s = await SessionRepository(db).get(session_id)
                conn = await manager.get_endpoint_for_user(s.user_id)
                skills = await AgentSkillEnableRepository(db).list_enabled_for_agent(
                    s.agent_config_id
                )
                materialize_enabled_skills(
                    base_root=Path(settings.sandbox_base_root),
                    user_id=s.user_id,
                    work_subdir=s.work_subdir,
                    skills=skills,
                    store=store,
                )
                wd = "." if settings.sandbox_provisioner == "docker" else s.work_subdir
                return await build_run_turn_request(
                    db,
                    s,
                    sandbox_endpoint=conn.endpoint,
                    sandbox_token=conn.token,
                    user_message=user_content,
                    exclude_message_id=user_msg_id,
                    enabled_skills=skills,
                    work_subdir=wd,
                    is_scheduled_run=is_scheduled_run,
                )

        policy = RetryPolicy.from_settings(settings)
        overflow_used = transient_used = total_used = 0
        # 回合前压缩(P0,与 runner 同口径):上一回合 last_context_tokens 超阈值 → 先折叠,
        # _assemble 随后读到新摘要。压缩耗时在心跳内续租;调用方本就在等本函数返回,无锁尾巴。
        async with session_heartbeat(session_id, settings.session_heartbeat_seconds):
            await maybe_compact_before_turn(session_id, settings=settings)
        current = await _assemble()
        async with session_heartbeat(session_id, settings.session_heartbeat_seconds):
            while True:
                total_used += 1
                try:
                    response = await run_turn_via_worker(settings.worker_endpoint, current)
                    break
                except grpc.aio.AioRpcError as exc:
                    action = policy.decide(
                        exc.code(),
                        overflow_used=overflow_used,
                        transient_used=transient_used,
                        total_used=total_used,
                    )
                    if action == RetryAction.COMPACT_RETRY:
                        if not await force_compact(session_id, settings=settings):
                            raise HeadlessOverflow() from exc
                        overflow_used += 1
                        current = await _assemble()
                        continue
                    if action == RetryAction.BACKOFF_RETRY:
                        await asyncio.sleep(policy.backoff_seconds(transient_used))
                        transient_used += 1
                        continue
                    if classify(exc.code()) == "overflow":
                        raise HeadlessOverflow() from exc
                    raise HeadlessWorkerError(exc.code()) from exc

        commons = [msg_from_proto(p) for p in response.new_messages]
        persisted: list[Message] = []
        async with get_sessionmaker()() as db:
            repo = MessageRepository(db)
            for common in commons:
                row = await repo.append(
                    session_id,
                    Message(
                        session_id=session_id,
                        seq=0,
                        role=common.role.value,
                        content=common_to_content(common),
                    ),
                )
                persisted.append(row)
            await SessionRepository(db).set_context_tokens(session_id, response.context_tokens)
            await db.commit()
        # agent 主动工具副作用(remember + schedule_task),独立事务、best-effort。
        await run_tool_side_effects(session_id, commons)

        async with get_sessionmaker()() as db:
            s = await SessionRepository(db).get(session_id)
            if s.title is None:
                spawn_title_generation(session_id, settings=settings)

        final_text = next(
            (m.content.get("text", "") for m in reversed(persisted) if m.role == "assistant"), ""
        )
        return HeadlessResult(
            new_messages=persisted,
            final_text=final_text,
            stop_reason=response.stop_reason,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )
    finally:
        async with get_sessionmaker()() as db:
            try:
                await SessionRepository(db).release(session_id)
                await db.commit()
            except Exception:
                logger.exception("headless: release lock failed for %s", session_id)
