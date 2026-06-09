import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from agent_cloud_backend.models.memory_entry import MemoryEntry
from agent_cloud_backend.repositories.base import BaseRepository


class MemoryConflict(Exception):
    """并发写同一 (scope, owner) 的版本冲突;调用方应重读当前块后重试。"""


class MemoryEntryRepository(BaseRepository[MemoryEntry]):
    model = MemoryEntry

    async def get_current(self, scope: str, owner_id: uuid.UUID) -> MemoryEntry | None:
        """当前块 = 该 (scope, owner) 下 version 最大的那一行。"""
        r = await self.session.execute(
            select(MemoryEntry)
            .where(MemoryEntry.scope == scope, MemoryEntry.owner_id == owner_id)
            .order_by(MemoryEntry.version.desc())
            .limit(1)
        )
        return r.scalars().first()

    async def write_version(
        self,
        scope: str,
        owner_id: uuid.UUID,
        content: str,
        source_session_id: uuid.UUID | None,
        *,
        expected_version: int,
    ) -> MemoryEntry:
        """写入新版本快照 version=expected+1;若有人已写该版本(唯一约束冲突)→ MemoryConflict。"""
        entry = MemoryEntry(
            scope=scope,
            owner_id=owner_id,
            content=content,
            version=expected_version + 1,
            source_session_id=source_session_id,
        )
        self.session.add(entry)
        try:
            await self.session.flush()
        except IntegrityError as e:
            raise MemoryConflict(str(e)) from e
        return entry

    async def prune(self, scope: str, owner_id: uuid.UUID, keep: int) -> int:
        """只保留最近 keep 个版本,删掉更老的;返回删除数。"""
        ids = (
            await self.session.execute(
                select(MemoryEntry.id)
                .where(MemoryEntry.scope == scope, MemoryEntry.owner_id == owner_id)
                .order_by(MemoryEntry.version.desc())
                .offset(keep)
            )
        ).scalars().all()
        for rid in ids:
            obj = await self.session.get(MemoryEntry, rid)
            if obj is not None:
                await self.session.delete(obj)
        return len(ids)

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
