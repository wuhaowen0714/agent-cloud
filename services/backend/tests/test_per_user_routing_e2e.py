import uuid

import pytest_asyncio
from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.main import create_app
from agent_cloud_backend.models.sandbox_registry import SandboxRegistry
from agent_cloud_backend.sandbox.deps import get_sandbox_manager
from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner
from agent_cloud_backend.sandbox.manager import SandboxManager
from agent_cloud_common import CompletionResult, Message, Role, ToolCall, Usage
from agent_cloud_worker.provider import FakeProvider
from agent_cloud_worker.server import create_server as create_worker_server
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker


def _writer_provider(path, content):
    return FakeProvider(
        [
            CompletionResult(
                message=Message(
                    role=Role.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            id="c1", name="write_file", arguments={"path": path, "content": content}
                        )
                    ],
                ),
                usage=Usage(input_tokens=1, output_tokens=1),
            ),
            CompletionResult(
                message=Message(role=Role.ASSISTANT, text="done"),
                usage=Usage(input_tokens=1, output_tokens=1),
            ),
        ]
    )


@pytest_asyncio.fixture
async def stack(engine, tmp_path):
    # The worker resolves a provider per request via the factory, keyed by the
    # agent's provider name; each user's agent uses a distinct provider name so
    # each turn writes distinct content.
    maker = async_sessionmaker(engine, expire_on_commit=False)
    providers = {}

    def factory(model, provider, key_ref):
        # provider name carries which script to use (test wires it via agent.provider)
        return providers[provider]

    worker_server, wport = await create_worker_server(provider_factory=factory, port=0)
    manager = SandboxManager(
        provisioner=InProcessProvisioner(base_root=tmp_path), sessionmaker=maker
    )

    async def _override_session():
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_settings] = lambda: Settings(worker_endpoint=f"localhost:{wport}")
    app.dependency_overrides[get_sandbox_manager] = lambda: manager
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, tmp_path, maker, providers
    await worker_server.stop(None)


async def _user_session(client, email, provider_name):
    uid = (await client.post("/users", json={"email": email})).json()["id"]
    aid = (
        await client.post(
            "/agent-configs",
            json={"user_id": uid, "name": "c", "model": "m", "provider": provider_name},
        )
    ).json()["id"]
    sid = (await client.post("/sessions", json={"user_id": uid, "agent_config_id": aid})).json()[
        "id"
    ]
    return uid, sid


async def test_two_users_get_isolated_sandboxes(stack):
    client, base, maker, providers = stack
    providers["pa"] = _writer_provider("a.txt", "alpha")
    providers["pb"] = _writer_provider("b.txt", "beta")

    uid_a, sid_a = await _user_session(client, "a@e.com", "pa")
    uid_b, sid_b = await _user_session(client, "b@e.com", "pb")

    ra = await client.post(f"/sessions/{sid_a}/turn", json={"content": "write a"})
    rb = await client.post(f"/sessions/{sid_b}/turn", json={"content": "write b"})
    assert ra.status_code == 200 and rb.status_code == 200

    # each user's file is under its OWN per-user sandbox dir; not visible to the other
    assert (base / str(uid_a) / f"sessions/{sid_a}" / "a.txt").read_text() == "alpha"
    assert (base / str(uid_b) / f"sessions/{sid_b}" / "b.txt").read_text() == "beta"
    assert not (base / str(uid_a)).joinpath(f"sessions/{sid_b}", "b.txt").exists()

    # registry has one active sandbox per user
    async with maker() as db:
        rows = (
            (await db.execute(select(SandboxRegistry).where(SandboxRegistry.status == "active")))
            .scalars()
            .all()
        )
    by_user = {r.user_id for r in rows}
    assert by_user == {uuid.UUID(uid_a), uuid.UUID(uid_b)}
