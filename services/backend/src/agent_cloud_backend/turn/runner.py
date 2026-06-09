from __future__ import annotations

import asyncio
import logging
import uuid

import grpc
from agent_cloud_common import TurnDone
from agent_cloud_common.codec import turn_event_from_proto

from agent_cloud_backend.config import Settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.turn import worker_client
from agent_cloud_backend.turn.compaction import force_compact, maybe_compact_after_turn
from agent_cloud_backend.turn.heartbeat import session_heartbeat
from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
from agent_cloud_backend.turn.memory_extract import apply_remember_calls
from agent_cloud_backend.turn.messages import common_to_content
from agent_cloud_backend.turn.retry import RetryAction, RetryPolicy, classify
from agent_cloud_backend.turn.sse import error_sse, turn_event_to_sse

logger = logging.getLogger(__name__)


async def _persist(session_id: uuid.UUID, new_messages, context_tokens: int) -> list[str]:
    ids: list[str] = []
    async with get_sessionmaker()() as db:
        repo = MessageRepository(db)
        for common in new_messages:
            row = await repo.append(
                session_id,
                Message(
                    session_id=session_id,
                    seq=0,
                    role=common.role.value,
                    content=common_to_content(common),
                ),
            )
            ids.append(str(row.id))
        # 记录本回合上下文占用(供 /status 显示);与消息同事务落库。
        await SessionRepository(db).set_context_tokens(session_id, context_tokens)
        await db.commit()
    # agent 主动记忆:独立事务、best-effort(记忆写冲突重试绝不拖垮上面的消息持久化)。
    try:
        await apply_remember_calls(session_id, new_messages)
    except Exception:
        logger.exception("apply_remember_calls failed for session %s", session_id)
    return ids


async def _release_session_lock(session_id: uuid.UUID) -> None:
    try:
        async with get_sessionmaker()() as db:
            await SessionRepository(db).release(session_id)
            await db.commit()
    except Exception:
        logger.exception("failed to release session lock for session %s", session_id)


async def _finalize(active: ActiveTurn, session_id: uuid.UUID) -> None:
    """唤醒订阅者(done)+ 释放会话锁。包进 shield 调用,二次取消下仍跑完。"""
    await active.finish()
    await _release_session_lock(session_id)


async def drain_hub(hub: TurnHub) -> None:
    """关停时调用:取消所有 runner、等其收尾,再兜底释放仍在 hub 里(含从未启动
    就被取消、其 finally 未跑的)会话锁,避免锁卡到 600s 租约过期(I2/I3)。"""
    tasks = hub.all_tasks()
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    for sid in hub.session_ids():
        await _release_session_lock(sid)
        hub.remove(sid)


async def run_turn(
    hub: TurnHub,
    active: ActiveTurn,
    *,
    worker_endpoint: str,
    request,
    reassemble,  # async () -> RunTurnRequest;重试时重新组装(读到压缩后的会话)
    session_id: uuid.UUID,
    heartbeat_interval: float,
    settings: Settings,
) -> None:
    """独立任务:消费 worker 流 → 落库;可恢复失败在回合内透明自动重试(spec: turn-recovery)。

    断连不取消本任务(由 asyncio.create_task 起)。重试前发 reset 事件让前端清屏;
    reset 标记留在补播缓冲里,重连补播自洽(回放旧增量→遇 reset 清掉→回放重试后内容)。
    """
    policy = RetryPolicy.from_settings(settings)
    overflow_used = transient_used = total_used = 0
    ctx_tokens = 0
    current = request
    try:
        async with session_heartbeat(session_id, heartbeat_interval):
            while True:
                total_used += 1
                try:
                    async for proto_event in worker_client.stream_turn_via_worker(
                        worker_endpoint, current
                    ):
                        event = turn_event_from_proto(proto_event)
                        if isinstance(event, TurnDone):
                            ctx_tokens = event.context_tokens
                            message_ids = await _persist(
                                session_id, event.new_messages, ctx_tokens
                            )
                            await active.emit(
                                {
                                    "type": "turn_done",
                                    "usage": {
                                        "input_tokens": event.usage.input_tokens,
                                        "output_tokens": event.usage.output_tokens,
                                    },
                                    "message_ids": message_ids,
                                    "stop_reason": event.stop_reason,
                                }
                            )
                        else:
                            await active.emit(turn_event_to_sse(event))
                    # 回合成功收尾 → 主动压缩(仍在心跳内续租)→ 结束
                    await maybe_compact_after_turn(
                        session_id, ctx_tokens, model=current.agent.model, settings=settings
                    )
                    return
                except grpc.aio.AioRpcError as exc:
                    action = policy.decide(
                        exc.code(),
                        overflow_used=overflow_used,
                        transient_used=transient_used,
                        total_used=total_used,
                    )
                    if action == RetryAction.COMPACT_RETRY:
                        progressed = await force_compact(session_id, settings=settings)
                        if not progressed:
                            # 无可折叠(仅剩最近一条仍超窗)→ 不可恢复,别让用户白重试
                            await active.emit(
                                {
                                    "type": "error",
                                    "message": "context too large to compact; "
                                    "please start a new session",
                                    "recoverable": False,
                                }
                            )
                            return
                        overflow_used += 1
                        await active.emit({"type": "reset"})  # 清屏;标记留缓冲,补播自洽
                        current = await reassemble()
                        continue
                    if action == RetryAction.BACKOFF_RETRY:
                        await asyncio.sleep(policy.backoff_seconds(transient_used))
                        transient_used += 1
                        await active.emit({"type": "reset"})
                        current = await reassemble()
                        continue
                    # GIVE_UP:超窗到上限(压缩多轮仍超窗)→ 与"无进展"一致地不可恢复;
                    # 瞬时耗尽 → recoverable(code 在 _RECOVERABLE);fatal → 不可恢复。
                    if classify(exc.code()) == "overflow":
                        await active.emit(
                            {
                                "type": "error",
                                "message": "context too large to compact; "
                                "please start a new session",
                                "recoverable": False,
                            }
                        )
                    else:
                        await active.emit(error_sse(exc.code()))
                    return
    except asyncio.CancelledError:
        # 主动取消(含退避/重试间隙)→ 转成干净的终止事件,让 finally 收尾(不再 re-raise)
        await active.emit({"type": "error", "message": "turn cancelled", "recoverable": False})
    except Exception:
        logger.exception("turn run failed for session %s", session_id)
        await active.emit({"type": "error", "message": "the turn failed", "recoverable": False})
    finally:
        # 进入 finally 后,务必在后续(二次)取消下仍完成:从 Hub 移除 + 唤醒订阅者 +
        # 释放锁。hub.remove 同步先做(无 await,必成);finish+release 包进 shield 的
        # 一个协程,二次取消时其内部仍跑完(C1)。
        hub.remove(session_id)
        await asyncio.shield(_finalize(active, session_id))
