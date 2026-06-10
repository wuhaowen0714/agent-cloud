import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud_backend.models.base import Base, TimestampMixin, uuid_pk


class UserModel(Base, TimestampMixin):
    """用户自定义模型名(模型选单的「自定义」段;预设/在用不落库)。"""

    __tablename__ = "user_models"
    __table_args__ = (UniqueConstraint("user_id", "model", name="uq_user_models_user_model"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    model: Mapped[str] = mapped_column(nullable=False)
