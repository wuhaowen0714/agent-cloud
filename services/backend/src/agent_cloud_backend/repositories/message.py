import uuid

from sqlalchemy import delete, func, select

from agent_cloud_backend.models.message import Message
from agent_cloud_backend.repositories.base import BaseRepository


class MessageRepository(BaseRepository[Message]):
    model = Message

    async def _next_seq(self, session_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.max(Message.seq), -1)).where(Message.session_id == session_id)
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

    async def get_in_session(
        self, session_id: uuid.UUID, message_id: uuid.UUID
    ) -> Message | None:
        """按 id 取消息,但仅当它属于给定会话(否则视为不存在,防跨会话引用)。"""
        m = await self.session.get(Message, message_id)
        return m if m is not None and m.session_id == session_id else None

    async def delete_from_seq(self, session_id: uuid.UUID, target_seq: int) -> int:
        """删除该会话 seq >= target 的全部消息(回滚:删后缀)。返回删除条数。"""
        result = await self.session.execute(
            delete(Message).where(Message.session_id == session_id, Message.seq >= target_seq)
        )
        return result.rowcount

    async def copy_prefix_to(
        self, src_session_id: uuid.UUID, dst_session_id: uuid.UUID, below_seq: int
    ) -> None:
        """把源会话 seq < below 的消息保序复制到目标会话(fork:复制前缀),保留 seq/role/content。"""
        for m in await self.list_by_session(src_session_id):
            if m.seq >= below_seq:
                continue
            self.session.add(
                Message(
                    session_id=dst_session_id,
                    seq=m.seq,
                    role=m.role,
                    content=m.content,
                    model=m.model,
                    tokens=m.tokens,
                )
            )
        await self.session.flush()
