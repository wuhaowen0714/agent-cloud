from __future__ import annotations

import logging
import uuid

from agent_cloud_backend.turn.memory_extract import apply_remember_calls
from agent_cloud_backend.turn.notify_apply import apply_notify_calls
from agent_cloud_backend.turn.schedule_apply import apply_schedule_task_calls

logger = logging.getLogger(__name__)


async def run_tool_side_effects(session_id: uuid.UUID, new_messages) -> None:
    """落库后处理 agent 主动工具(remember + schedule_task + notify)的副作用。各自独立
    best-effort,互不影响,也绝不拖垮消息持久化。流式(runner._persist)与非流式(headless)共用。"""
    for fn in (apply_remember_calls, apply_schedule_task_calls, apply_notify_calls):
        try:
            await fn(session_id, new_messages)
        except Exception:
            logger.exception("%s failed for session %s", fn.__name__, session_id)
