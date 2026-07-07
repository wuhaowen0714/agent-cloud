import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from agent_cloud_backend.models.notification import Notification
from agent_cloud_backend.repositories.base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    model = Notification

    async def list_undelivered(self, user_id: uuid.UUID) -> list[Notification]:
        result = await self.session.execute(
            select(Notification)
            .where(Notification.user_id == user_id, Notification.delivered_at.is_(None))
            # id tiebreaker:同事务落的多条 created_at 相同(PG now() 事务内恒定),
            # 无 tiebreaker 时补投顺序/超限截断非确定(审查 MEDIUM-1)
            .order_by(Notification.created_at, Notification.id)
        )
        return list(result.scalars().all())

    async def mark_delivered(self, ids: list[uuid.UUID], user_id: uuid.UUID) -> None:
        """把这些(且属本人)通知置已送达。幂等;空 ids 直接返回。"""
        if not ids:
            return
        await self.session.execute(
            update(Notification)
            .where(Notification.id.in_(ids), Notification.user_id == user_id)
            .values(delivered_at=datetime.now(UTC))
        )
