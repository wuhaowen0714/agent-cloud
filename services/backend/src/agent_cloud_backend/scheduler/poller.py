from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from agent_cloud_backend.config import Settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.repositories.scheduled_task import ScheduledTaskRepository
from agent_cloud_backend.scheduler import schedule
from agent_cloud_backend.scheduler.runner import run_scheduled_task

logger = logging.getLogger(__name__)


async def scheduler_loop(settings: Settings) -> None:
    """lifespan 后台任务:周期轮询到期定时任务。单次失败不退出循环。"""
    while True:
        try:
            await poll_once(settings)
        except Exception:
            logger.exception("scheduler poll pass failed")
        await asyncio.sleep(settings.scheduler_poll_interval_seconds)


async def poll_once(settings: Settings) -> list[dict]:
    """取到期任务 → 先推进 next_run/标记 running(同一加锁事务内)→ 提交释放行锁 → 并发跑回合。
    返回本轮实际派去执行的任务快照列表。"""
    now = datetime.now(UTC)
    to_run: list[dict] = []
    async with get_sessionmaker()() as db:
        repo = ScheduledTaskRepository(db)
        due = await repo.select_due_for_update(
            now,
            limit=settings.scheduler_batch_size,
            run_lease_seconds=settings.scheduler_run_lease_seconds,
        )
        for t in due:
            grace = schedule.grace_seconds(
                t.schedule_kind, t.schedule_expr, t.schedule_tz, t.next_run_at
            )
            new_next = schedule.next_run_after(
                t.schedule_kind, t.schedule_expr, t.schedule_tz, prev=t.next_run_at, now=now
            )
            stale = grace > 0 and t.next_run_at < now - timedelta(seconds=grace)
            t.next_run_at = new_next
            if new_next is None:
                t.enabled = False  # once 跑完即停
            if stale:
                t.last_status = "skipped"  # 陈旧周期任务:快进、本轮不补跑
                t.last_run_at = now
            else:
                t.running_since = now
                to_run.append(
                    {
                        "id": t.id,
                        "user_id": t.user_id,
                        "agent_config_id": t.agent_config_id,
                        "name": t.name,
                        "prompt": t.prompt,
                        "origin_session_id": t.origin_session_id,
                    }
                )
        await db.commit()  # 释放行锁(回合执行前)

    if not to_run:
        return to_run
    sem = asyncio.Semaphore(settings.scheduler_max_concurrent_runs)

    async def _guarded(snap: dict) -> None:
        async with sem:
            await run_scheduled_task(snap, settings)

    await asyncio.gather(*(_guarded(s) for s in to_run), return_exceptions=True)
    return to_run
