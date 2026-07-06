from __future__ import annotations

import logging
import uuid

from agent_cloud_backend.api.push import push_to_user
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.notification import Notification
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository

logger = logging.getLogger(__name__)

# 防 LLM 生成超长正文撑爆存储/响应(OS 通知本就截断)。title/body 入库前各自封顶。
TITLE_MAX = 200
BODY_MAX = 2000


def _accepted_notify_calls(new_messages) -> list:
    """worker【已接受】(tool_result 非错误)、按 call_id 去重的 notify 调用。"""
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
            if c.name == "notify" and c.id in ok_ids and c.id not in seen:
                seen.add(c.id)
                calls.append(c)
    return calls


async def apply_notify_calls(session_id: uuid.UUID, new_messages) -> int:
    """把本回合 agent 主动 notify 的调用落成 notifications 行(spec 2026-06-14)。

    独立事务、best-effort。服务端重校验 enabled_tools;user_id/origin 取自服务端会话(不取 LLM)。
    与 schedule_task 不同:**无自排期护栏**——定时运行里 notify 正是主用例。返回新建行数。
    """
    calls = _accepted_notify_calls(new_messages)
    if not calls:
        return 0
    async with get_sessionmaker()() as db:
        s = await db.get(Session, session_id)
        if s is None:
            return 0
        agent = await AgentConfigRepository(db).get(s.agent_config_id)
        enabled = list(agent.enabled_tools) if agent else []
        if enabled and "notify" not in enabled:
            return 0
        created = 0
        accepted: list[tuple[str, str]] = []
        for c in calls:
            args = c.arguments or {}
            title, body = args.get("title"), args.get("body")
            if not all(isinstance(x, str) and x.strip() for x in (title, body)):
                continue
            db.add(
                Notification(
                    user_id=s.user_id,
                    title=title.strip()[:TITLE_MAX],
                    body=body.strip()[:BODY_MAX],
                    origin_session_id=session_id,
                )
            )
            accepted.append((title.strip()[:TITLE_MAX], body.strip()[:BODY_MAX]))
            created += 1
        await db.commit()
        user_id = s.user_id
    # 手机端 WS 推送(落库之后、事务之外;best-effort——无设备在线就静默,web 轮询兜底)
    for title, body in accepted:
        try:
            await push_to_user(
                user_id,
                {"type": "notify", "title": title, "body": body, "session_id": str(session_id)},
            )
        except Exception:
            logger.exception("push notify failed for session %s", session_id)
    return created
