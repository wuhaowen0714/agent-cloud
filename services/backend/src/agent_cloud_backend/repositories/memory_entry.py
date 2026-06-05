import uuid

from sqlalchemy import select

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
        entry = MemoryEntry(
            scope=scope,
            owner_id=owner_id,
            content=content,
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
