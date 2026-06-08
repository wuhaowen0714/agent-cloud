import base64
import os
import uuid as _uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.files.deps import get_file_store
from agent_cloud_backend.files.store import LocalFileStore
from agent_cloud_backend.main import create_app
from agent_cloud_backend.models import Base
from agent_cloud_backend.sandbox.deps import get_sandbox_manager
from agent_cloud_backend.sandbox.manager import SandboxManager
from agent_cloud_backend.skills.deps import get_object_store
from agent_cloud_backend.skills.store import LocalObjectStore
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

# 凭据 API(/credentials)依赖 AGENT_CLOUD_CREDENTIAL_KEY;测试注入一个固定 32B 主密钥。
os.environ.setdefault("AGENT_CLOUD_CREDENTIAL_KEY", base64.b64encode(b"\x07" * 32).decode())


class _FakeProvisioner:
    async def spawn(self, user_id):
        return _uuid.uuid4(), f"fake-sandbox:{user_id}"

    async def stop(self, sandbox_id):
        return None


def override_sandbox_manager_fake(app, engine):
    """让端点用一个 FakeProvisioner 的 manager(不起真沙箱)。"""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    manager = SandboxManager(provisioner=_FakeProvisioner(), sessionmaker=maker)
    app.dependency_overrides[get_sandbox_manager] = lambda: manager
    return manager


def override_object_store(app, root):
    """让 skill 端点写到隔离的临时对象存储目录。"""
    store = LocalObjectStore(root)
    app.dependency_overrides[get_object_store] = lambda: store
    return store


def override_file_store(app, root):
    """让文件端点(及从工作区安装技能)写到隔离的临时工作区根。"""
    store = LocalFileStore(str(root))
    app.dependency_overrides[get_file_store] = lambda: store
    return store


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
async def client(engine, tmp_path) -> AsyncIterator[AsyncClient]:
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override
    override_sandbox_manager_fake(app, engine)
    override_object_store(app, tmp_path / "objstore")
    override_file_store(app, tmp_path / "filestore")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def client_noraise(engine, tmp_path) -> AsyncIterator[AsyncClient]:
    """Like ``client`` but does NOT re-raise app exceptions: unhandled errors
    surface as real 500 responses (as a production HTTP client would see them),
    instead of propagating into the test. Needed to assert 5xx behavior."""
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override
    override_sandbox_manager_fake(app, engine)
    override_object_store(app, tmp_path / "objstore")
    override_file_store(app, tmp_path / "filestore")
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def register_user(client: AsyncClient, email: str | None = None) -> tuple[str, str]:
    """注册一个新用户;返回 (access_token, user_id)。不改 client 的默认 header。"""
    email = email or f"{_uuid.uuid4()}@e.com"
    r = await client.post("/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 201, r.text
    body = r.json()
    return body["access_token"], body["user"]["id"]


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient) -> AsyncClient:
    """已登录的 client:注册一个用户并把 access token 设为默认 Authorization header。
    需要 user_id 的测试可读 client.user_id;需要多用户的用 register_user() 另注册。"""
    access, user_id = await register_user(client)
    client.headers["Authorization"] = f"Bearer {access}"
    client.user_id = user_id  # type: ignore[attr-defined]
    return client


@pytest_asyncio.fixture
async def auth_client_noraise(client_noraise: AsyncClient) -> AsyncClient:
    access, user_id = await register_user(client_noraise)
    client_noraise.headers["Authorization"] = f"Bearer {access}"
    client_noraise.user_id = user_id  # type: ignore[attr-defined]
    return client_noraise
