"""会话标题自动生成:回合成功收尾后的 fire-and-forget 钩子(spec 2026-06-11)。"""

from __future__ import annotations

import asyncio
import logging
import uuid

from agent_cloud.v1 import worker_pb2
from sqlalchemy import select, update

from agent_cloud_backend.config import Settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.turn.credentials import resolve_agent_key
from agent_cloud_backend.turn.worker_client import generate_title_via_worker

logger = logging.getLogger(__name__)

# fire-and-forget 任务持引用,防止被 GC 提前回收
_TITLE_TASKS: set[asyncio.Task] = set()


def spawn_title_generation(session_id: uuid.UUID, *, settings: Settings) -> None:
    """回合成功收尾后调用:异步生成会话标题,绝不阻塞/影响回合本身。"""
    task = asyncio.create_task(generate_session_title(session_id, settings=settings))
    _TITLE_TASKS.add(task)
    task.add_done_callback(_TITLE_TASKS.discard)


async def generate_session_title(session_id: uuid.UUID, *, settings: Settings) -> bool:
    """title 为空时,基于首条 user 消息让 LLM 起名。返回是否写入。

    三段式,事务绝不横跨 RPC(审查 H1:横跨会把池连接钉在 idle-in-transaction
    整个 LLM 调用时长,测试里曾把下个用例的 DROP TABLE 锁死):
      1) 短事务读齐(title 空检 / 首条提问 / agent 凭据)→ 关闭;
      2) 调 worker(带 deadline);
      3) 条件 UPDATE `WHERE title IS NULL` 单语句写——生成期间用户手动改名 →
         rowcount=0,自动放弃,无覆盖窗口。
    best-effort:任何失败只记日志、留 null(下一回合自然重试)。
    """
    try:
        async with get_sessionmaker()() as db:
            s = await db.get(Session, session_id)
            if s is None or s.title is not None:
                return False
            first = (
                await db.execute(
                    select(Message)
                    .where(Message.session_id == session_id, Message.role == "user")
                    .order_by(Message.seq)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if first is None:
                return False
            text = (first.content or {}).get("text", "")
            if not text.strip():
                return False
            agent = await AgentConfigRepository(db).get(s.agent_config_id)
            if agent is None:
                return False
            # BYO-Key:用本人凭据(无/不属本人 → ("","") 回退全局)。key 仅经 worker。
            api_key, base_url = await resolve_agent_key(
                db, agent.key_ref or "", s.user_id, settings
            )
            model, provider = agent.model, agent.provider

        title = await generate_title_via_worker(
            settings.worker_endpoint,
            worker_pb2.GenerateTitleRequest(
                agent=worker_pb2.Agent(
                    model=model, provider=provider, api_key=api_key, base_url=base_url
                ),
                user_message=text,
            ),
        )
        if not title:
            return False  # LLM 清不出标题:放弃,不写空串

        async with get_sessionmaker()() as db:
            res = await db.execute(
                update(Session)
                .where(Session.id == session_id, Session.title.is_(None))
                .values(title=title)
            )
            await db.commit()
            return bool(res.rowcount)
    except Exception:
        logger.warning("session title generation failed for %s", session_id, exc_info=True)
        return False
