from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from agent_cloud_backend.config import Settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.scheduled_task import ScheduledTaskRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.sandbox.deps import get_sandbox_manager
from agent_cloud_backend.skills.deps import get_object_store
from agent_cloud_backend.turn.headless import SessionBusy, execute_turn_headless

logger = logging.getLogger(__name__)

CRON_HINT = (
    "[你正作为定时任务运行。把你的报告/结果作为最终回复产出即可,系统会自动呈现给用户;"
    "不要自己尝试投递。若确实没有新内容可报,只回复 [SILENT](别的什么都不写)。]"
)
_BJ = ZoneInfo("Asia/Shanghai")


async def run_scheduled_task(snap: dict, settings: Settings) -> None:
    """执行一个到期定时任务:建新会话 → 跑无头回合 → [SILENT]/状态回写 → 回执。

    snap: {id, user_id, agent_config_id, name, prompt, origin_session_id}。
    next_run_at 已由轮询器在执行前推进(at-most-once),这里只管跑 + 回写状态。
    """
    name = snap["name"]
    stamp = datetime.now(UTC).astimezone(_BJ).strftime("%m-%d %H:%M")
    title = f"📅 {name} · {stamp}"
    async with get_sessionmaker()() as db:
        s = await SessionRepository(db).create_for(
            snap["user_id"],
            snap["agent_config_id"],
            title,
            model=settings.resolve_default_model(),
            scheduled_task_id=snap["id"],
            unread=True,
        )
        await db.commit()
        session_id = s.id

    status, error, delivery_error = "ok", None, None
    try:
        result = await execute_turn_headless(
            session_id,
            f"{CRON_HINT}\n\n{snap['prompt']}",
            settings=settings,
            manager=get_sandbox_manager(),
            store=get_object_store(),
            is_scheduled_run=True,
        )
        if result.final_text.strip().startswith("[SILENT]"):
            status = "skipped"
    except SessionBusy:
        status, error = "error", "session busy"
    except Exception as exc:
        logger.exception("scheduled task %s run failed", snap["id"])
        status, error = "error", str(exc)[:2000]

    if status == "skipped":
        async with get_sessionmaker()() as db:
            await SessionRepository(db).set_unread(session_id, False)
            await db.commit()

    # 回执(仅 agent 排的期 + 跑成了 + 发起会话空闲,避免与活跃回合抢 seq)
    origin = snap.get("origin_session_id")
    if origin and status == "ok":
        try:
            async with get_sessionmaker()() as db:
                o = await SessionRepository(db).get(origin)
                if o is not None and o.status == "idle":
                    await MessageRepository(db).append(
                        origin,
                        Message(
                            session_id=origin,
                            seq=0,
                            role="assistant",
                            content={
                                "text": f"📅 定时任务「{name}」已运行 → 结果见新会话",
                                "tool_calls": [],
                                "tool_results": [],
                            },
                        ),
                    )
                    await db.commit()
        except Exception:
            logger.exception("scheduled task %s receipt failed", snap["id"])
            delivery_error = "receipt append failed"

    async with get_sessionmaker()() as db:
        await ScheduledTaskRepository(db).set_result(
            snap["id"],
            status=status,
            last_run_session_id=session_id,
            error=error,
            delivery_error=delivery_error,
        )
        await db.commit()
