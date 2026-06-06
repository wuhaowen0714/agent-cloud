from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker

from agent_cloud_backend.repositories.sandbox_registry import SandboxRegistryRepository
from agent_cloud_backend.sandbox.provisioner import SandboxProvisioner


class SandboxManager:
    def __init__(
        self,
        provisioner: SandboxProvisioner,
        sessionmaker: async_sessionmaker,
        idle_ttl_seconds: int = 1800,
    ) -> None:
        self._provisioner = provisioner
        self._sessionmaker = sessionmaker
        self._idle_ttl_seconds = idle_ttl_seconds

    async def get_endpoint_for_user(self, user_id: uuid.UUID) -> str:
        async with self._sessionmaker() as db:
            repo = SandboxRegistryRepository(db)
            existing = await repo.get_active_for_user(user_id)
            if existing is not None:
                await repo.touch(existing.id)
                await db.commit()
                return existing.endpoint

        # spawn outside the DB transaction (provisioning may be slow)
        sandbox_id, endpoint = await self._provisioner.spawn(user_id)
        async with self._sessionmaker() as db:
            repo = SandboxRegistryRepository(db)
            await repo.register(sandbox_id, user_id, endpoint)
            await db.commit()
        return endpoint

    async def reap_idle(self) -> int:
        """标记并停掉空闲超 TTL 的 sandbox。返回回收数量。"""
        cutoff = datetime.now(UTC) - timedelta(seconds=self._idle_ttl_seconds)
        async with self._sessionmaker() as db:
            repo = SandboxRegistryRepository(db)
            stale = await repo.list_active_idle_since(cutoff)
            stale_ids = [s.id for s in stale]
            for sandbox_id in stale_ids:
                await repo.mark_dead(sandbox_id)
            await db.commit()

        for sandbox_id in stale_ids:
            await self._provisioner.stop(sandbox_id)
        return len(stale_ids)
