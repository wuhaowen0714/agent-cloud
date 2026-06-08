import uuid

from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud_backend.models.base import Base, TimestampMixin, uuid_pk


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    # argon2id 哈希;server_default="" 让迁移对现有行安全(dev 数据会重建,空哈希无法登录)
    password_hash: Mapped[str] = mapped_column(nullable=False, server_default="")
