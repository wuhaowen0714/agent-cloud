import uuid

from sqlalchemy import func, select

from agent_cloud_backend.models.memory_entry import MemoryEntry
from agent_cloud_backend.repositories.base import BaseRepository


class MemoryEntryRepository(BaseRepository[MemoryEntry]):
    model = MemoryEntry

    async def append(
        self,
        scope: str,
        owner_id: uuid.UUID,
        content: str,
        source_session_id: uuid.UUID | None = None,
    ) -> MemoryEntry:
        # 旧接口(将在 T9 移除):自增 version 以满足 (scope,owner,version) 唯一约束。
        nxt = (
            await self.session.execute(
                select(func.coalesce(func.max(MemoryEntry.version), 0) + 1).where(
                    MemoryEntry.scope == scope, MemoryEntry.owner_id == owner_id
                )
            )
        ).scalar_one()
        entry = MemoryEntry(
            scope=scope,
            owner_id=owner_id,
            content=content,
            version=nxt,
            source_session_id=source_session_id,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_for_context(
        self, scope: str, owner_id: uuid.UUID, limit: int = 50
    ) -> list[MemoryEntry]:
        # v1:取最近 N 条。未来引入向量检索时,这里改为 top-k(接口不变)。
        result = await self.session.execute(
            select(MemoryEntry)
            .where(MemoryEntry.scope == scope, MemoryEntry.owner_id == owner_id)
            # created_at (server_default now()) is constant within a transaction,
            # so a stable tiebreaker is required for deterministic ordering.
            .order_by(MemoryEntry.created_at.desc(), MemoryEntry.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
