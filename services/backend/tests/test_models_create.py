from sqlalchemy import text


async def test_all_tables_created(engine):
    expected = {
        "users",
        "agent_configs",
        "sessions",
        "messages",
        "context_documents",
        "memory_entries",
        "skills",
        "agent_skill_enables",
    }
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        tables = {r[0] for r in rows}
    assert expected.issubset(tables)
