import uuid
from datetime import datetime

from sqlalchemy import DateTime, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud_backend.models.base import Base, uuid_pk


class ContextDocument(Base):
    __tablename__ = "context_documents"
    __table_args__ = (
        UniqueConstraint("scope", "type", "owner_id", name="uq_ctxdoc_scope_type_owner"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    scope: Mapped[str] = mapped_column(nullable=False)  # user | agent
    type: Mapped[str] = mapped_column(nullable=False)  # USER | AGENTS | SOUL | ...
    owner_id: Mapped[uuid.UUID] = mapped_column(index=True, nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
