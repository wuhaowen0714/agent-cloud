import uuid

from sqlalchemy import func, select

from agent_cloud_backend.models.message import Message
from agent_cloud_backend.repositories.base import BaseRepository


class MessageRepository(BaseRepository[Message]):
    model = Message

    async def _next_seq(self, session_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.max(Message.seq), -1)).where(
                Message.session_id == session_id
            )
        )
        return int(result.scalar_one()) + 1

    async def append(self, session_id: uuid.UUID, message: Message) -> Message:
        message.seq = await self._next_seq(session_id)
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_by_session(self, session_id: uuid.UUID) -> list[Message]:
        result = await self.session.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.seq)
        )
        return list(result.scalars().all())
