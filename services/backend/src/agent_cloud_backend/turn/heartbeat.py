from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator

from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.repositories.session import SessionRepository

logger = logging.getLogger(__name__)


async def _loop(session_id: uuid.UUID, interval: float) -> None:
    # 用独立 DB 会话续租(不能复用端点的请求会话——并发使用同一 AsyncSession 不安全)。
    while True:
        await asyncio.sleep(interval)
        try:
            async with get_sessionmaker()() as db:
                await SessionRepository(db).heartbeat(session_id)
                await db.commit()
        except Exception:
            logger.exception("session %s heartbeat failed", session_id)


@contextlib.asynccontextmanager
async def session_heartbeat(session_id: uuid.UUID, interval: float) -> AsyncIterator[None]:
    """回合进行期间周期续租会话锁;退出时取消续租任务。

    interval 应远小于 try_acquire 的 lease(默认 600s),使长回合的租约在被并发回合
    判定为过期前就被刷新。快回合里 sleep 尚未触发即被取消,不产生额外 DB 写。
    """
    task = asyncio.create_task(_loop(session_id, interval))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
