import uuid
from datetime import datetime

from sqlalchemy import func, select, update

from agent_cloud_backend.models.sandbox_registry import SandboxRegistry
from agent_cloud_backend.repositories.base import BaseRepository


class SandboxRegistryRepository(BaseRepository[SandboxRegistry]):
    model = SandboxRegistry

    async def register(
        self, sandbox_id: uuid.UUID, user_id: uuid.UUID, endpoint: str, token: str = ""
    ) -> SandboxRegistry:
        sb = SandboxRegistry(
            id=sandbox_id, user_id=user_id, endpoint=endpoint, auth_token=token, status="active"
        )
        self.session.add(sb)
        await self.session.flush()
        return sb

    async def get_active_for_user(self, user_id: uuid.UUID) -> SandboxRegistry | None:
        result = await self.session.execute(
            select(SandboxRegistry)
            .where(SandboxRegistry.user_id == user_id, SandboxRegistry.status == "active")
            # id.desc() is a defensive tiebreaker for rows sharing a created_at
            # (mirrors the memory_entry convention) so ordering is deterministic.
            .order_by(SandboxRegistry.created_at.desc(), SandboxRegistry.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def touch(self, sandbox_id: uuid.UUID) -> None:
        await self.session.execute(
            update(SandboxRegistry)
            .where(SandboxRegistry.id == sandbox_id)
            .values(last_used_at=func.now())
        )

    async def mark_dead(self, sandbox_id: uuid.UUID) -> None:
        await self.session.execute(
            update(SandboxRegistry).where(SandboxRegistry.id == sandbox_id).values(status="dead")
        )

    async def list_active_idle_since(self, cutoff: datetime) -> list[SandboxRegistry]:
        result = await self.session.execute(
            select(SandboxRegistry).where(
                SandboxRegistry.status == "active", SandboxRegistry.last_used_at < cutoff
            )
        )
        return list(result.scalars().all())
