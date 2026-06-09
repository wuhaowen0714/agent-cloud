import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from agent_cloud_backend.models.memory_entry import MemoryEntry
from agent_cloud_backend.repositories.base import BaseRepository

# 自整合单块记忆(spec 2026-06-09):每行 = 某 (scope, owner_id) 记忆块的一个完整快照版本;
# "当前块" = version 最大的那行;唯一约束 (scope,owner_id,version) 提供乐观并发。


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
        keep = max(keep, 1)  # 永不删到 0 条(否则会把刚写入的当前块也删掉)
        ids = (
            (
                await self.session.execute(
                    select(MemoryEntry.id)
                    .where(MemoryEntry.scope == scope, MemoryEntry.owner_id == owner_id)
                    .order_by(MemoryEntry.version.desc())
                    .offset(keep)
                )
            )
            .scalars()
            .all()
        )
        for rid in ids:
            obj = await self.session.get(MemoryEntry, rid)
            if obj is not None:
                await self.session.delete(obj)
        return len(ids)
