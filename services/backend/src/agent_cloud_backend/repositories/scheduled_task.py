import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from agent_cloud_backend.models.scheduled_task import ScheduledTask
from agent_cloud_backend.repositories.base import BaseRepository


class ScheduledTaskRepository(BaseRepository[ScheduledTask]):
    model = ScheduledTask

    async def list_by_user(self, user_id: uuid.UUID) -> list[ScheduledTask]:
        result = await self.session.execute(
            select(ScheduledTask)
            .where(ScheduledTask.user_id == user_id)
            .order_by(ScheduledTask.created_at, ScheduledTask.id)
        )
        return list(result.scalars().all())

    async def get_owned(self, task_id: uuid.UUID, user_id: uuid.UUID) -> ScheduledTask | None:
        t = await self.session.get(ScheduledTask, task_id)
        return t if t is not None and t.user_id == user_id else None

    async def select_due_for_update(
        self, now: datetime, *, limit: int, run_lease_seconds: int
    ) -> list[ScheduledTask]:
        """到期且未在跑(或租约已过)的任务,加行锁、跳过别人锁住的(多副本安全)。"""
        lease_cutoff = now - timedelta(seconds=run_lease_seconds)
        result = await self.session.execute(
            select(ScheduledTask)
            .where(
                ScheduledTask.enabled.is_(True),
                ScheduledTask.next_run_at.isnot(None),
                ScheduledTask.next_run_at <= now,
                (ScheduledTask.running_since.is_(None))
                | (ScheduledTask.running_since < lease_cutoff),
            )
            .order_by(ScheduledTask.next_run_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def set_result(
        self,
        task_id: uuid.UUID,
        *,
        status: str,
        last_run_session_id: uuid.UUID | None,
        error: str | None,
        delivery_error: str | None,
    ) -> None:
        """回写一次运行结果并清 running_since(单条 UPDATE,不读 ORM 对象)。"""
        await self.session.execute(
            update(ScheduledTask)
            .where(ScheduledTask.id == task_id)
            .values(
                last_run_at=datetime.now(UTC),
                last_status=status,
                last_run_session_id=last_run_session_id,
                last_error=error,
                last_delivery_error=delivery_error,
                running_since=None,
            )
        )
