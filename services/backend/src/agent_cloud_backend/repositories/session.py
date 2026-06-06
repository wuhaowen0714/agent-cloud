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
        # Caveat: long turns are NOT heartbeated, so `lease_seconds` must exceed
        # the maximum expected turn duration or a still-running turn could be
        # taken over mid-flight. Per-turn heartbeat / lease-renewal is a later
        # refinement.
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

    async def release(self, session_id: uuid.UUID) -> None:
        await self.session.execute(
            update(Session).where(Session.id == session_id).values(status="idle")
        )
