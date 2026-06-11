"""sandbox auth token

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-06-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default="":存量 active 沙箱(迁移前起、无 token env)取回空 token,
    # worker 调用带空 metadata,沙箱无 token 配置→放行;新沙箱才带 token。过渡平滑。
    op.add_column(
        "sandbox_registry",
        sa.Column("auth_token", sa.String(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sandbox_registry", "auth_token")
