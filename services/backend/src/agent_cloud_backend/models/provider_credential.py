import uuid

from sqlalchemy import ForeignKey, LargeBinary
from sqlalchemy.dialects.postgresql import JSONB
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
    # 该 provider 下可用的模型清单(图三用户手填,可多个);session 选 provider 后从这里出 model 候选。
    models: Mapped[list] = mapped_column(JSONB, default=list, nullable=False, server_default="[]")
