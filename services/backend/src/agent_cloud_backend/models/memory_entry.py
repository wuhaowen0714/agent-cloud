import uuid

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud_backend.models.base import Base, TimestampMixin, uuid_pk

# 自整合单块记忆(spec 2026-06-09):每行 = 某 (scope, owner_id) 记忆块的一个完整快照版本;
# "当前块" = version 最大的那行。唯一约束 (scope,owner_id,version) 提供乐观并发。


class MemoryEntry(Base, TimestampMixin):
    __tablename__ = "memory_entries"
    __table_args__ = (
        UniqueConstraint("scope", "owner_id", "version", name="uq_memory_scope_owner_version"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    scope: Mapped[str] = mapped_column(index=True, nullable=False)  # user | agent
    owner_id: Mapped[uuid.UUID] = mapped_column(index=True, nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
