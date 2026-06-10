import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select, update

from agent_cloud_backend.models.session import Session
from agent_cloud_backend.repositories.base import BaseRepository


class SessionRepository(BaseRepository[Session]):
    model = Session

    async def create_for(
        self, user_id: uuid.UUID, agent_config_id: uuid.UUID, title: str | None
    ) -> Session:
        # 用户级共享工作空间:同一用户的所有 agent/session 共用
        # base_root/<user_id>/workspace/(base 本就按 user_id 划分且跨沙箱重建稳定)。
        # 原先按 session 隔离(sessions/<id>),现改为固定子目录以便文件共享。
        s = Session(
            id=uuid.uuid4(),
            user_id=user_id,
            agent_config_id=agent_config_id,
            title=title,
            work_subdir="workspace",
        )
        self.session.add(s)
        await self.session.flush()
        return s

    async def list_by_user(self, user_id: uuid.UUID) -> list[Session]:
        result = await self.session.execute(select(Session).where(Session.user_id == user_id))
        return list(result.scalars().all())

    async def user_ids_with_running_session(self, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        """给定用户里,哪些当前有 status='running' 的会话(reap 时用来跳过,避免长回合被中途回收)。"""
        if not user_ids:
            return set()
        result = await self.session.execute(
            select(Session.user_id)
            .where(Session.user_id.in_(user_ids), Session.status == "running")
            .distinct()
        )
        return set(result.scalars().all())

    async def try_acquire(self, session_id: uuid.UUID, lease_seconds: int = 600) -> bool:
        # Acquire if the session is idle OR its existing lock is stale (older
        # than the lease), which lets a later turn take over after a crashed
        # request strands the row in `running`.
        #
        # A live long turn is kept from being taken over by ``heartbeat()`` (the
        # turn endpoint renews ``last_active_at`` periodically), so the lease only
        # expires for a turn that actually died -- crash-recovery takeover without
        # stealing a still-running turn.
        cutoff = datetime.now(UTC) - timedelta(seconds=lease_seconds)
        result = await self.session.execute(
            update(Session)
            .where(
                Session.id == session_id,
                or_(Session.status == "idle", Session.last_active_at < cutoff),
            )
            .values(status="running", last_active_at=func.now())
        )
        return result.rowcount == 1

    async def heartbeat(self, session_id: uuid.UUID) -> bool:
        """续租:仅当会话仍 ``running`` 时刷新 ``last_active_at``;返回是否续上。

        回合进行中由端点周期调用,使租约只在回合**真正死亡**时才过期,从而长回合
        不会被同会话的并发回合抢锁(5b 评审里 .skills 在 reader 下被 rmtree 的根因)。
        """
        result = await self.session.execute(
            update(Session)
            .where(Session.id == session_id, Session.status == "running")
            .values(last_active_at=func.now())
        )
        return result.rowcount == 1

    async def release(self, session_id: uuid.UUID) -> None:
        await self.session.execute(
            update(Session).where(Session.id == session_id).values(status="idle")
        )

    async def set_context_tokens(self, session_id: uuid.UUID, tokens: int) -> None:
        """记录最近一回合 worker 报告的上下文 token 占用(供 /status 显示)。"""
        await self.session.execute(
            update(Session).where(Session.id == session_id).values(last_context_tokens=tokens)
        )

    async def delete_if_idle(self, session_id: uuid.UUID, lease_seconds: int = 600) -> bool:
        """原子删除:仅 idle 或租约过期(crash 残留)才删;与回合 try_acquire 靠行锁
        天然串行,不存在「检查后被开跑再删」的 TOCTOU。返回是否删了。"""
        cutoff = datetime.now(UTC) - timedelta(seconds=lease_seconds)
        result = await self.session.execute(
            delete(Session).where(
                Session.id == session_id,
                or_(Session.status == "idle", Session.last_active_at < cutoff),
            )
        )
        return result.rowcount == 1

    async def delete_idle_for_agent(self, agent_id: uuid.UUID, lease_seconds: int = 600) -> None:
        """删除该 agent 的全部可删会话(同上守卫);留下的(在跑)由调用方数出并 409。"""
        cutoff = datetime.now(UTC) - timedelta(seconds=lease_seconds)
        await self.session.execute(
            delete(Session).where(
                Session.agent_config_id == agent_id,
                or_(Session.status == "idle", Session.last_active_at < cutoff),
            )
        )

    async def count_for_agent(self, agent_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Session).where(Session.agent_config_id == agent_id)
        )
        return int(result.scalar_one())
