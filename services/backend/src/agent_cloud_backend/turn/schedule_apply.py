from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.scheduled_task import ScheduledTask
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.scheduler.schedule import (
    ScheduleError,
    first_run_at,
    validate_and_normalize,
)

logger = logging.getLogger(__name__)


def _accepted_schedule_task_calls(new_messages) -> list:
    """worker【已接受】(tool_result 非错误)、按 call_id 去重的 schedule_task 调用。"""
    ok_ids = {
        r.call_id
        for m in new_messages
        for r in (getattr(m, "tool_results", None) or [])
        if not r.is_error
    }
    seen: set[str] = set()
    calls = []
    for m in new_messages:
        for c in getattr(m, "tool_calls", None) or []:
            if c.name == "schedule_task" and c.id in ok_ids and c.id not in seen:
                seen.add(c.id)
                calls.append(c)
    return calls


async def apply_schedule_task_calls(session_id: uuid.UUID, new_messages) -> int:
    """把本回合 agent 主动 schedule_task 的调用落成 scheduled_tasks 行(spec 2026-06-13)。

    独立事务、best-effort。服务端权威校验:enabled_tools 重判 + 排期合法性 + **自排期护栏**
    (定时跑出来的会话不准再排期)。归属取自服务端会话,不取 LLM 给的。返回新建行数。
    """
    calls = _accepted_schedule_task_calls(new_messages)
    if not calls:
        return 0
    async with get_sessionmaker()() as db:
        s = await db.get(Session, session_id)
        if s is None:
            return 0
        if s.scheduled_task_id is not None:
            return 0  # 自排期护栏(纵深防御,即便 worker 漏暴露了工具)
        agent = await AgentConfigRepository(db).get(s.agent_config_id)
        enabled = list(agent.enabled_tools) if agent else []
        if enabled and "schedule_task" not in enabled:
            return 0
        now = datetime.now(UTC)
        created = 0
        for c in calls:
            args = c.arguments or {}
            name, prompt = args.get("name"), args.get("prompt")
            kind, expr = args.get("schedule_kind"), args.get("schedule_expr")
            tz = args.get("schedule_tz") or "Asia/Shanghai"
            if not all(isinstance(x, str) and x.strip() for x in (name, prompt, kind, expr)):
                continue
            try:
                norm = validate_and_normalize(kind, expr, tz)
                next_run = first_run_at(kind, norm, tz, now)
            except ScheduleError:
                logger.info(
                    "schedule_task: dropping invalid schedule from agent (%s/%s)", kind, expr
                )
                continue
            db.add(
                ScheduledTask(
                    user_id=s.user_id,
                    agent_config_id=s.agent_config_id,
                    name=name.strip(),
                    prompt=prompt.strip(),
                    schedule_kind=kind,
                    schedule_expr=norm,
                    schedule_tz=tz,
                    next_run_at=next_run,
                    origin_session_id=session_id,
                )
            )
            created += 1
        await db.commit()
        return created
