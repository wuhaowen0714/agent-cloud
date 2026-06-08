"""session summary fields

Revision ID: c1d2e3f4a5b6
Revises: 7a1b2c3d4e5f
Create Date: 2026-06-08 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "7a1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "sessions", sa.Column("summary", sa.Text(), nullable=False, server_default="")
    )
    op.add_column(
        "sessions",
        sa.Column("summary_through_seq", sa.Integer(), nullable=False, server_default="-1"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sessions", "summary_through_seq")
    op.drop_column("sessions", "summary")
