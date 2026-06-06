import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud_backend.models.base import Base, TimestampMixin, uuid_pk


class SandboxRegistry(Base, TimestampMixin):
    __tablename__ = "sandbox_registry"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(default="active", nullable=False)  # active | dead
    endpoint: Mapped[str] = mapped_column(nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # At most one *active* sandbox per user. The partial predicate lets any
    # number of historical `dead` rows coexist while serializing concurrent
    # spawns for the same user, so a double-`get_endpoint_for_user` race can't
    # create two active rows and split-route the user. (`create_all` honors
    # this in tests; the hand-written alembic migration creates it in prod --
    # autogenerate misses partial indexes.)
    __table_args__ = (
        Index(
            "uq_active_sandbox_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )
