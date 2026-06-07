import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from agent_cloud_backend.api import (
    agent_configs,
    agent_skills,
    context_documents,
    files,
    memory_entries,
    messages,
    sessions,
    skills,
    turn,
    users,
)

logger = logging.getLogger(__name__)


async def _reaper_loop(interval_seconds: float, manager) -> None:
    """周期性回收空闲沙箱。单次失败不退出循环(spec §4.1:接上原本无调用方的 reap_idle)。"""
    while True:
        # 先 reap 再 sleep:backend 重启后立刻回收上一进程遗留的空闲沙箱,不等满一个 interval。
        try:
            await manager.reap_idle()
        except Exception:
            logger.exception("sandbox reaper pass failed")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app):
    from agent_cloud_backend.config import get_settings
    from agent_cloud_backend.sandbox.deps import get_sandbox_manager

    settings = get_settings()
    manager = get_sandbox_manager()
    task = asyncio.create_task(_reaper_loop(settings.sandbox_reap_interval_seconds, manager))
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # 取消所有在跑的回合 Runner(独立任务),避免关停时 "task pending" 并让锁释放跑完。
        from agent_cloud_backend.turn.hub import get_turn_hub

        for t in get_turn_hub().all_tasks():
            t.cancel()


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
        users,
        agent_configs,
        sessions,
        messages,
        context_documents,
        memory_entries,
        turn,
        skills,
        agent_skills,
        files,
    ):
        app.include_router(module.router)

    return app


app = create_app()
