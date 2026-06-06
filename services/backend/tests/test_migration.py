import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def test_alembic_upgrade_creates_schema(migration_pg_url: str):
    # migration_pg_url is a dedicated, isolated container (its own empty
    # database), so the migration builds the schema from scratch and this test
    # is independent of test order -- no DROP SCHEMA reset needed.
    sync_url = migration_pg_url.replace("+asyncpg", "")  # alembic 检查用同步连接
    os.environ["AGENT_CLOUD_DATABASE_URL"] = migration_pg_url  # env.py online 用 async

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")

    engine = create_engine(sync_url)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
        tables = {r[0] for r in rows}
        # the hand-written partial unique index must be created by the migration
        # (autogenerate misses partial indexes, so this guards that migration)
        idx_rows = conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname='public' AND tablename='sandbox_registry'"
            )
        )
        indexes = {r[0] for r in idx_rows}
        skill_idx_rows = conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname='public' AND tablename='skills'"
            )
        )
        skill_indexes = {r[0] for r in skill_idx_rows}
    assert {
        "users",
        "agent_configs",
        "sessions",
        "messages",
        "context_documents",
        "memory_entries",
        "sandbox_registry",
        "skills",
        "agent_skill_enables",
    }.issubset(tables)
    assert "alembic_version" in tables
    assert "uq_active_sandbox_per_user" in indexes
    assert "uq_skill_user_name" in skill_indexes
