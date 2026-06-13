import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from agent_cloud_backend.api import (
    agent_configs,
    agent_skills,
    auth,
    context_documents,
    credentials,
    files,
    memory_entries,
    messages,
    scheduled_tasks,
    sessions,
    skills,
    terminal,
    turn,
    user_models,
)
from agent_cloud_backend.scheduler.poller import scheduler_loop

logger = logging.getLogger(__name__)


async def _reaper_loop(interval_seconds: float, manager) -> None:
    """周期性回收空闲沙箱。单次失败不退出循环(spec §4.1:接上原本无调用方的 reap_idle)。"""
    while True:
        # 先 reap 再 sleep:backend 重启后立刻回收上一进程遗留的空闲沙箱,不等满一个 interval。
        try:
            await manager.reap_idle()
        except Exception:
            logger.exception("sandbox reaper pass failed")
        # 同一周期顺带做"空闲会话记忆提炼"(spec 2026-06-09:空闲触发,内含轮次闸)。
        try:
            from agent_cloud_backend.config import get_settings
            from agent_cloud_backend.turn.memory_extract import scan_idle_and_extract

            await scan_idle_and_extract(get_settings())
        except Exception:
            logger.exception("memory idle-extract pass failed")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app):
    from agent_cloud_backend.config import get_settings
    from agent_cloud_backend.sandbox.deps import get_sandbox_manager

    settings = get_settings()
    manager = get_sandbox_manager()
    task = asyncio.create_task(_reaper_loop(settings.sandbox_reap_interval_seconds, manager))
    # 定时任务轮询器(spec 2026-06-13;可经 scheduler_enabled 关闭)。多副本可全开,
    # select_due_for_update 的 FOR UPDATE SKIP LOCKED 保证同一到期任务不被重复触发。
    sched_task = (
        asyncio.create_task(scheduler_loop(settings)) if settings.scheduler_enabled else None
    )
    try:
        yield
    finally:
        bg_tasks = [t for t in (task, sched_task) if t is not None]
        for t in bg_tasks:
            t.cancel()
        for t in bg_tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        # 取消所有在跑的回合 Runner,等其收尾,并兜底释放残留会话锁(否则关停时
        # shield 的释放可能没跑完、或从未启动的 runner 没机会释放 → 锁卡到租约过期)。
        from agent_cloud_backend.turn.hub import get_turn_hub
        from agent_cloud_backend.turn.runner import drain_hub

        await drain_hub(get_turn_hub())


def create_app() -> FastAPI:
    app = FastAPI(title="Agent Cloud Backend", lifespan=lifespan)

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(_request: Request, _exc: IntegrityError) -> JSONResponse:
        # FK / unique / not-null violations are client errors. Return a generic
        # 409 instead of leaking the raw DB message (table/column/SQL) in a 500.
        # The request's DB session is closed by the get_session dependency's
        # context manager, discarding the aborted transaction.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "integrity constraint violation"},
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    for module in (
        auth,
        agent_configs,
        sessions,
        messages,
        context_documents,
        memory_entries,
        turn,
        scheduled_tasks,
        skills,
        agent_skills,
        files,
        credentials,
        user_models,
        terminal,
    ):
        app.include_router(module.router)

    return app


app = create_app()
