import json

import pytest_asyncio
from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.main import create_app
from agent_cloud_backend.sandbox.deps import get_sandbox_manager
from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner
from agent_cloud_backend.sandbox.manager import SandboxManager
from agent_cloud_common import CompletionResult, Message, Role, ToolCall, Usage
from agent_cloud_worker.provider import FakeProvider
from agent_cloud_worker.server import create_server as create_worker_server
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker


def _parse_sse(text: str) -> list[dict]:
    out = []
    for block in text.strip().split("\n\n"):
        line = block.strip()
        if line.startswith("data:"):
            out.append(json.loads(line[len("data:") :].strip()))
    return out


@pytest_asyncio.fixture
async def stack(engine, tmp_path):
    # The streaming proxy generator runs after the endpoint returns and opens a
    # fresh session via ``db.get_sessionmaker()`` (the module-global, NOT the
    # request-scoped DI session overridden below). Point that global sessionmaker
    # at the testcontainer engine so the ``turn_done`` persist and lock release
    # hit the test DB instead of the configured (localhost) database_url. Mirror
    # the unit-test ``_patch_global_sessionmaker`` helper, with save/restore since
    # fixtures have no monkeypatch.
    import agent_cloud_backend.db as db_module

    _saved = db_module._sessionmaker
    db_module._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    provider = FakeProvider(
        [
            CompletionResult(
                message=Message(
                    role=Role.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="write_file",
                            arguments={"path": "hi.txt", "content": "yo"},
                        )
                    ],
                ),
                usage=Usage(input_tokens=2, output_tokens=3),
            ),
            CompletionResult(
                message=Message(role=Role.ASSISTANT, text="all done"),
                usage=Usage(input_tokens=2, output_tokens=3),
            ),
        ]
    )
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_session():
        async with maker() as s:
            yield s

    provisioner = InProcessProvisioner(base_root=tmp_path)
    manager = SandboxManager(provisioner=provisioner, sessionmaker=maker)

    app = create_app()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_settings] = lambda: Settings(worker_endpoint=f"localhost:{wport}")
    app.dependency_overrides[get_sandbox_manager] = lambda: manager
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, tmp_path
    await worker_server.stop(None)
    await provisioner.stop_all()
    db_module._sessionmaker = _saved


async def test_full_streaming_turn(stack):
    client, base = stack
    uid = (await client.post("/users", json={"email": "e2e@example.com"})).json()["id"]
    aid = (
        await client.post(
            "/agent-configs", json={"user_id": uid, "name": "c", "model": "m", "provider": "fake"}
        )
    ).json()["id"]
    sid = (await client.post("/sessions", json={"user_id": uid, "agent_config_id": aid})).json()[
        "id"
    ]

    resp = await client.post(f"/sessions/{sid}/turn/stream", json={"content": "write it"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    kinds = [e["type"] for e in events]
    assert "tool_call_start" in kinds and "tool_result" in kinds
    assert "text_delta" in kinds  # the "all done" delta
    assert kinds[-1] == "turn_done"
    assert events[-1]["stop_reason"] == "end_turn" and len(events[-1]["message_ids"]) == 3

    # tool executed in the per-user shared workspace ({uid}/workspace)
    assert (base / str(uid) / "workspace" / "hi.txt").read_text() == "yo"
    # DB persisted user + assistant + tool + assistant
    listed = (await client.get(f"/sessions/{sid}/messages")).json()
    assert [m["role"] for m in listed] == ["user", "assistant", "tool", "assistant"]
