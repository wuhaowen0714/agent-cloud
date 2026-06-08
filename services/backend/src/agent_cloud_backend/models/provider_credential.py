import uuid

from sqlalchemy import ForeignKey, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud_backend.models.base import Base, TimestampMixin, uuid_pk


class ProviderCredential(Base, TimestampMixin):
    __tablename__ = "provider_credentials"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(nullable=False)
    base_url: Mapped[str] = mapped_column(nullable=False, default="")
    api_key_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    masked: Mapped[str] = mapped_column(nullable=False, default="")  # 展示掩码,免解密即可列出
