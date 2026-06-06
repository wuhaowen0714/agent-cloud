from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker

from agent_cloud_backend.repositories.sandbox_registry import SandboxRegistryRepository
from agent_cloud_backend.sandbox.provisioner import SandboxProvisioner

logger = logging.getLogger(__name__)


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
        """标记并停掉空闲超 TTL 的 sandbox。返回回收数量。

        Caveat: ``last_used_at`` is only touched at turn *start* (see
        ``get_endpoint_for_user``), not during a turn, so ``idle_ttl_seconds``
        must exceed the maximum expected turn duration -- otherwise a sandbox
        serving a long-running turn could be reaped mid-flight. Per-turn
        touch/heartbeat (and skipping reap of sandboxes whose session is
        ``running``) is a Plan 4b/later refinement; mirrors the session-lock
        lease caveat in ``repositories/session.py``.

        Each sandbox is stopped *first* (guarded) and only marked ``dead`` on a
        successful stop, so a stop failure leaves the row ``active`` (reapable
        on the next pass) instead of orphaning a still-running sandbox whose row
        was already flipped to ``dead`` -- a permanent leak.
        """
        cutoff = datetime.now(UTC) - timedelta(seconds=self._idle_ttl_seconds)
        async with self._sessionmaker() as db:
            stale = await SandboxRegistryRepository(db).list_active_idle_since(cutoff)
            stale_ids = [s.id for s in stale]

        reaped = 0
        for sandbox_id in stale_ids:
            try:
                await self._provisioner.stop(sandbox_id)
            except Exception:
                logger.exception(
                    "failed to stop idle sandbox %s; will retry next reap", sandbox_id
                )
                continue
            async with self._sessionmaker() as db:
                await SandboxRegistryRepository(db).mark_dead(sandbox_id)
                await db.commit()
            reaped += 1
        return reaped
