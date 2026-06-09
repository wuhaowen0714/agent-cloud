"""memory versioning

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-06-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a5b6c7d8e9"
down_revision: str | Sequence[str] | None = "e3f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "memory_entries", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "sessions",
        sa.Column("memory_through_seq", sa.Integer(), nullable=False, server_default="-1"),
    )
    # 回填:同 (scope, owner_id) 的旧"逐条"行各给递增 version,避免唯一约束冲突;
    # 最新一条即成为"当前块",下次提炼会整体重写。
    op.execute(
        """
        UPDATE memory_entries m SET version = sub.rn
        FROM (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY scope, owner_id ORDER BY created_at, id) AS rn
            FROM memory_entries
        ) sub
        WHERE m.id = sub.id
        """
    )
    op.create_unique_constraint(
        "uq_memory_scope_owner_version", "memory_entries", ["scope", "owner_id", "version"]
    )
    op.alter_column("memory_entries", "version", server_default=None)
    op.alter_column("sessions", "memory_through_seq", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_memory_scope_owner_version", "memory_entries", type_="unique")
    op.drop_column("sessions", "memory_through_seq")
    op.drop_column("memory_entries", "version")
