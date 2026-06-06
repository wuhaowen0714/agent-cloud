from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.main import create_app
from agent_cloud_backend.models import Base
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def pg_url() -> AsyncIterator[str]:
    with PostgresContainer("postgres:16", driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest.fixture
def migration_pg_url() -> AsyncIterator[str]:
    """A dedicated, isolated database for the Alembic migration test.

    The session-scoped ``pg_url`` container is shared with the ORM ``engine``
    fixture (which runs ``create_all``) and accumulates ``alembic_version``
    state, so a migration test running against it depends on test order and
    needs schema-reset hacks. This fixture spins its own container (the image
    is cached, so startup is fast) so the migration builds the schema from a
    truly empty database, independent of any other test.
    """
    with PostgresContainer("postgres:16", driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest_asyncio.fixture
async def engine(pg_url: str):
    eng = create_async_engine(pg_url, future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s


@pytest_asyncio.fixture
async def client(engine) -> AsyncIterator[AsyncClient]:
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def client_noraise(engine) -> AsyncIterator[AsyncClient]:
    """Like ``client`` but does NOT re-raise app exceptions: unhandled errors
    surface as real 500 responses (as a production HTTP client would see them),
    instead of propagating into the test. Needed to assert 5xx behavior."""
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
