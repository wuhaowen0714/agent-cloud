import uuid

from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud_backend.models.base import Base, TimestampMixin, uuid_pk

# 注:embedding 向量列在引入向量检索的后续 Plan 中添加;此处不加物理列。


class MemoryEntry(Base, TimestampMixin):
    __tablename__ = "memory_entries"

    id: Mapped[uuid.UUID] = uuid_pk()
    scope: Mapped[str] = mapped_column(index=True, nullable=False)  # user | agent
    owner_id: Mapped[uuid.UUID] = mapped_column(index=True, nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
