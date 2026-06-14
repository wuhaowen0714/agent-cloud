import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud_backend.models.base import Base, TimestampMixin, uuid_pk


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    origin_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ix_notifications_undelivered",
            "user_id",
            "created_at",
            postgresql_where=text("delivered_at IS NULL"),
        ),
    )
