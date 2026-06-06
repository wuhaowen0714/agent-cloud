"""add skills + agent_skill_enables

Revision ID: 7a1b2c3d4e5f
Revises: 118b49942e83
Create Date: 2026-06-07 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7a1b2c3d4e5f"
down_revision: str | Sequence[str] | None = "118b49942e83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("requires", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("package_ref", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_skill_user_name"),
    )
    op.create_index(op.f("ix_skills_user_id"), "skills", ["user_id"], unique=False)
    op.create_table(
        "agent_skill_enables",
        sa.Column("agent_config_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["agent_config_id"], ["agent_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_config_id", "skill_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("agent_skill_enables")
    op.drop_index(op.f("ix_skills_user_id"), table_name="skills")
    op.drop_table("skills")
