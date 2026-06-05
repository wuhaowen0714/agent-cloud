import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def test_alembic_upgrade_creates_schema(pg_url: str):
    sync_url = pg_url.replace("+asyncpg", "")  # alembic 检查用同步连接
    os.environ["AGENT_CLOUD_DATABASE_URL"] = pg_url  # env.py online 用 async

    # pg_url is a session-scoped shared container; other tests (engine/client fixtures)
    # may have already created ORM tables on it. Reset to a clean schema so this test
    # validates that the migration itself builds the schema from scratch, order-independent.
    engine = create_engine(sync_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
        tables = {r[0] for r in rows}
    assert {"users", "agent_configs", "sessions", "messages",
            "context_documents", "memory_entries"}.issubset(tables)
    assert "alembic_version" in tables
