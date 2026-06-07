import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update

from agent_cloud_backend.models.session import Session
from agent_cloud_backend.repositories.base import BaseRepository


class SessionRepository(BaseRepository[Session]):
    model = Session

    async def create_for(
        self, user_id: uuid.UUID, agent_config_id: uuid.UUID, title: str | None
    ) -> Session:
        s = Session(
            id=uuid.uuid4(),
            user_id=user_id,
            agent_config_id=agent_config_id,
            title=title,
            work_subdir="",
        )
        s.work_subdir = f"sessions/{s.id}"
        self.session.add(s)
        await self.session.flush()
        return s

    async def list_by_user(self, user_id: uuid.UUID) -> list[Session]:
        result = await self.session.execute(select(Session).where(Session.user_id == user_id))
        return list(result.scalars().all())

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
