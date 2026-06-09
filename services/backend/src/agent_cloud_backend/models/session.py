import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud_backend.models.base import Base, TimestampMixin, uuid_pk


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    agent_config_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_configs.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    title: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(default="idle", nullable=False)  # idle | running
    work_subdir: Mapped[str] = mapped_column(nullable=False)
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 会话压缩(spec §7):此前历史折叠成的摘要 + 已折叠到的最大 seq(之后的消息逐字保留)。
    summary: Mapped[str] = mapped_column(default="", nullable=False)
    summary_through_seq: Mapped[int] = mapped_column(default=-1, nullable=False)
    # 智能体记忆(spec 2026-06-09):已提炼进记忆的最大消息 seq(每条最多被提炼一次)。
    memory_through_seq: Mapped[int] = mapped_column(default=-1, nullable=False)
    # 最近一回合 worker 报告的上下文 token 占用(供 /status 显示;未跑过回合则为 NULL)。
    last_context_tokens: Mapped[int | None] = mapped_column(nullable=True)
