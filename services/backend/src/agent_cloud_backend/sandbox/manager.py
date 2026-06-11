from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from agent_cloud_backend.repositories.sandbox_registry import SandboxRegistryRepository
from agent_cloud_backend.sandbox.provisioner import SandboxProvisioner

logger = logging.getLogger(__name__)

# 返回 endpoint 是否存活。生产 provisioner 注入真实实现(见 sandbox/health.py)。
HealthCheck = Callable[[str], Awaitable[bool]]


@dataclass(frozen=True)
class SandboxConn:
    """worker 连沙箱所需:endpoint + gRPC 鉴权 token(token 空=沙箱开放,inprocess/旧)。"""

    endpoint: str
    token: str


class SandboxManager:
    def __init__(
        self,
        provisioner: SandboxProvisioner,
        sessionmaker: async_sessionmaker,
        idle_ttl_seconds: int = 1800,
        health_check: HealthCheck | None = None,
    ) -> None:
        self._provisioner = provisioner
        self._sessionmaker = sessionmaker
        self._idle_ttl_seconds = idle_ttl_seconds
        self._health_check = health_check

    async def get_endpoint_for_user(self, user_id: uuid.UUID) -> SandboxConn:
        dead_sandbox_id: uuid.UUID | None = None
        async with self._sessionmaker() as db:
            repo = SandboxRegistryRepository(db)
            existing = await repo.get_active_for_user(user_id)
            if existing is not None:
                # 若注入了 health_check,先探活再复用;未注入(进程内/开发,恒存活)
                # 则信任该行。探活失败 = 沙箱/worker 已死:标记 dead 不再路由,落到
                # 下方重建一个新的(spec §10)。
                if self._health_check is None or await self._health_check(existing.endpoint):
                    await repo.touch(existing.id)
                    await db.commit()
                    return SandboxConn(existing.endpoint, existing.auth_token)
                await repo.mark_dead(existing.id)
                await db.commit()
                dead_sandbox_id = existing.id

        if dead_sandbox_id is not None:
            # 已在登记表标记 dead(不会再被路由);停掉是尽力清理,失败不阻断重建。
            try:
                await self._provisioner.stop(dead_sandbox_id)
            except Exception:
                logger.exception("failed to stop dead sandbox %s", dead_sandbox_id)

        # spawn outside the DB transaction (provisioning may be slow)
        sandbox_id, endpoint, token = await self._provisioner.spawn(user_id)
        async with self._sessionmaker() as db:
            repo = SandboxRegistryRepository(db)
            try:
                await repo.register(sandbox_id, user_id, endpoint, token)
                await db.commit()
            except IntegrityError:
                # Lost the spawn race: a concurrent caller already inserted the
                # active row (partial unique index). Discard our throwaway
                # sandbox and route to the winner so the user isn't split across
                # two sandboxes.
                await db.rollback()
                winner = await repo.get_active_for_user(user_id)
                await self._provisioner.stop(sandbox_id)
                return SandboxConn(winner.endpoint, winner.auth_token)
        return SandboxConn(endpoint, token)

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
        from agent_cloud_backend.repositories.session import SessionRepository

        cutoff = datetime.now(UTC) - timedelta(seconds=self._idle_ttl_seconds)
        async with self._sessionmaker() as db:
            stale = await SandboxRegistryRepository(db).list_active_idle_since(cutoff)
            # 跳过仍有 running 会话的用户:长回合期间 last_used_at 不续,
            # 避免该用户的沙箱被中途回收(spec §4.1)。
            busy = await SessionRepository(db).user_ids_with_running_session(
                [s.user_id for s in stale]
            )
            stale_ids = [s.id for s in stale if s.user_id not in busy]

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
