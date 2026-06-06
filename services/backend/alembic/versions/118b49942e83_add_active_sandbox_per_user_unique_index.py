"""add partial unique index for one active sandbox per user

Revision ID: 118b49942e83
Revises: 59592b11f009
Create Date: 2026-06-06 14:40:00.000000

Hand-written: alembic autogenerate does NOT detect partial (predicated)
indexes, so this is authored by hand. It enforces at most one ``active``
sandbox row per user, serializing concurrent ``get_endpoint_for_user`` spawns
so a race can't create two active rows and split-route the user.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "118b49942e83"
down_revision: str | Sequence[str] | None = "59592b11f009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "uq_active_sandbox_per_user",
        "sandbox_registry",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_active_sandbox_per_user", table_name="sandbox_registry")
