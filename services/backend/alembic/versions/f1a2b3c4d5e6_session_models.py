"""session-level model selection: sessions.model/credential_id, credential.models, drop agent model cols

Revision ID: f1a2b3c4d5e6
Revises: d5e6f7a8b9c0
Create Date: 2026-06-13

模型选择从 agent 级下放到 session 级。先给 sessions 加 model/credential_id 并从各自 agent
回填(老会话不丢配置),再给 credential 加 models 清单,最后 drop agent 的模型列。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_RE = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def upgrade() -> None:
    # 1) sessions 加列(model 先 nullable 以便回填;credential_id nullable)
    op.add_column("sessions", sa.Column("model", sa.String(), nullable=True))
    op.add_column("sessions", sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=True))

    # 2) 回填:model 取所属 agent 的 model;credential_id 取 agent.key_ref——仅当它是合法 uuid
    #    且确实指向一条存在的 credential(否则留 NULL=回退平台)。
    op.execute(
        "UPDATE sessions s SET model = ac.model "
        "FROM agent_configs ac WHERE s.agent_config_id = ac.id"
    )
    op.execute(
        f"""
        UPDATE sessions s SET credential_id = ac.key_ref::uuid
        FROM agent_configs ac
        WHERE s.agent_config_id = ac.id
          AND ac.key_ref IS NOT NULL AND ac.key_ref <> ''
          AND ac.key_ref ~ '{_UUID_RE}'
          AND EXISTS (SELECT 1 FROM provider_credentials pc WHERE pc.id = ac.key_ref::uuid)
        """
    )
    op.execute("UPDATE sessions SET model = 'DeepSeek-V4-Pro' WHERE model IS NULL OR model = ''")

    # 3) model 收紧为 NOT NULL;credential_id 加索引 + FK(删凭据时 SET NULL → 回退平台)
    op.alter_column("sessions", "model", nullable=False)
    op.create_index(op.f("ix_sessions_credential_id"), "sessions", ["credential_id"])
    op.create_foreign_key(
        "fk_sessions_credential_id",
        "sessions",
        "provider_credentials",
        ["credential_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 4) provider_credentials 加模型清单
    op.add_column(
        "provider_credentials",
        sa.Column(
            "models",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )

    # 5) drop agent 的模型相关列
    op.drop_column("agent_configs", "model")
    op.drop_column("agent_configs", "provider")
    op.drop_column("agent_configs", "thinking_level")
    op.drop_column("agent_configs", "key_ref")


def downgrade() -> None:
    op.add_column("agent_configs", sa.Column("model", sa.String(), nullable=True))
    op.add_column("agent_configs", sa.Column("provider", sa.String(), nullable=True))
    op.add_column("agent_configs", sa.Column("thinking_level", sa.String(), nullable=True))
    op.add_column("agent_configs", sa.Column("key_ref", sa.String(), nullable=True))
    op.execute(
        "UPDATE agent_configs ac SET model = COALESCE("
        "(SELECT s.model FROM sessions s WHERE s.agent_config_id = ac.id LIMIT 1), 'DeepSeek-V4-Pro')"
    )
    op.execute("UPDATE agent_configs SET provider = 'openai' WHERE provider IS NULL")
    op.alter_column("agent_configs", "model", nullable=False)
    op.alter_column("agent_configs", "provider", nullable=False)

    op.drop_column("provider_credentials", "models")
    op.drop_constraint("fk_sessions_credential_id", "sessions", type_="foreignkey")
    op.drop_index(op.f("ix_sessions_credential_id"), "sessions")
    op.drop_column("sessions", "credential_id")
    op.drop_column("sessions", "model")
