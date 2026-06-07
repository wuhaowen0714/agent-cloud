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


@pytest_asyncio.fixture
async def stack(engine, tmp_path):
    # 真 worker(FakeProvider:写文件再收尾);沙箱由 manager 的 InProcessProvisioner 起
    provider = FakeProvider(
        [
            CompletionResult(
                message=Message(
                    role=Role.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="write_file",
                            arguments={"path": "hello.txt", "content": "from-agent"},
                        )
                    ],
                ),
                usage=Usage(input_tokens=2, output_tokens=3),
            ),
            CompletionResult(
                message=Message(role=Role.ASSISTANT, text="done"),
                usage=Usage(input_tokens=2, output_tokens=3),
            ),
        ]
    )
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)

    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_session():
        async with maker() as sdb:
            yield sdb

    def _override_settings():
        return Settings(worker_endpoint=f"localhost:{wport}")

    provisioner = InProcessProvisioner(base_root=tmp_path)
    manager = SandboxManager(provisioner=provisioner, sessionmaker=maker)

    app = create_app()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_sandbox_manager] = lambda: manager
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, tmp_path
    await worker_server.stop(None)
    await provisioner.stop_all()


async def test_full_turn_through_all_layers(stack):
    client, base = stack
    uid = (await client.post("/users", json={"email": "e2e@example.com"})).json()["id"]
    aid = (
        await client.post(
            "/agent-configs",
            json={"user_id": uid, "name": "coder", "model": "m", "provider": "fake"},
        )
    ).json()["id"]
    sid = (await client.post("/sessions", json={"user_id": uid, "agent_config_id": aid})).json()[
        "id"
    ]

    r = await client.post(f"/sessions/{sid}/turn", json={"content": "write the file"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stop_reason"] == "end_turn"
    assert [m["role"] for m in body["messages"]] == ["assistant", "tool", "assistant"]

    # 工具真的在沙箱里执行了(每用户沙箱目录:{uid}/sessions/{sid})
    assert (base / str(uid) / f"sessions/{sid}" / "hello.txt").read_text() == "from-agent"

    # DB 落了 user + assistant + tool + assistant
    listed = (await client.get(f"/sessions/{sid}/messages")).json()
    assert [m["role"] for m in listed] == ["user", "assistant", "tool", "assistant"]
