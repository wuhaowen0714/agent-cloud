import pytest_asyncio
from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.main import create_app
from agent_cloud_backend.sandbox.deps import get_sandbox_manager
from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner
from agent_cloud_backend.sandbox.manager import SandboxManager
from agent_cloud_backend.skills.deps import get_object_store
from agent_cloud_backend.skills.store import LocalObjectStore
from agent_cloud_common import CompletionResult, Message, Role, ToolCall, Usage
from agent_cloud_worker.provider import FakeProvider
from agent_cloud_worker.server import create_server as create_worker_server
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker


@pytest_asyncio.fixture
async def skill_stack(engine, tmp_path):
    # FakeProvider:第一轮让 agent 读已物化的 SKILL.md,第二轮收尾。
    provider = FakeProvider(
        [
            CompletionResult(
                message=Message(
                    role=Role.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="read_file",
                            arguments={"path": ".skills/skill-creator/SKILL.md"},
                        )
                    ],
                ),
                usage=Usage(input_tokens=1, output_tokens=1),
            ),
            CompletionResult(
                message=Message(role=Role.ASSISTANT, text="read it"),
                usage=Usage(input_tokens=1, output_tokens=1),
            ),
        ]
    )
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_session():
        async with maker() as sdb:
            yield sdb

    # 关键:物化器用 settings.sandbox_base_root,provisioner 用同一 tmp_path,二者必须一致
    def _override_settings():
        return Settings(worker_endpoint=f"localhost:{wport}", sandbox_base_root=str(tmp_path))

    provisioner = InProcessProvisioner(base_root=tmp_path)
    manager = SandboxManager(provisioner=provisioner, sessionmaker=maker)
    store = LocalObjectStore(tmp_path / "obj")

    app = create_app()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_sandbox_manager] = lambda: manager
    app.dependency_overrides[get_object_store] = lambda: store
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, tmp_path
    await worker_server.stop(None)
    await provisioner.stop_all()


async def test_enabled_skill_is_materialized_and_readable(skill_stack):
    client, base = skill_stack
    reg = (
        await client.post(
            "/auth/register", json={"email": "ske2e@example.com", "password": "password123"}
        )
    ).json()
    uid = reg["user"]["id"]
    client.headers["Authorization"] = f"Bearer {reg['access_token']}"
    aid = (
        await client.post(
            "/agent-configs", json={"name": "coder", "model": "m", "provider": "fake"}
        )
    ).json()["id"]
    # 从内置 registry 安装 + 给该 agent 启用
    skill_id = (
        await client.post("/skills/install", json={"name": "skill-creator"})
    ).json()["id"]
    r = await client.put(f"/agent-configs/{aid}/skills", json={"skill_ids": [skill_id]})
    assert r.status_code == 200, r.text

    sid = (await client.post("/sessions", json={"agent_config_id": aid})).json()["id"]
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "use the skill"})
    assert r.status_code == 200, r.text
    assert r.json()["stop_reason"] == "end_turn"

    # 1) skill 物化到了用户级共享工作空间
    md = base / str(uid) / "workspace" / ".skills" / "skill-creator" / "SKILL.md"
    assert md.is_file()
    assert "skill-creator" in md.read_text()

    # 2) agent 确实读到了它(tool 消息回填了 SKILL.md 内容)
    listed = (await client.get(f"/sessions/{sid}/messages")).json()
    assert [m["role"] for m in listed] == ["user", "assistant", "tool", "assistant"]
    tool_msg = listed[2]
    results = tool_msg["content"]["tool_results"]
    assert results and "skill-creator" in results[0]["content"]
    assert results[0]["is_error"] is False


async def test_disabled_skill_not_materialized(skill_stack):
    # 装了但不给 agent 启用 → 不应物化到沙箱
    client, base = skill_stack
    reg = (
        await client.post(
            "/auth/register", json={"email": "skoff@example.com", "password": "password123"}
        )
    ).json()
    uid = reg["user"]["id"]
    client.headers["Authorization"] = f"Bearer {reg['access_token']}"
    aid = (
        await client.post(
            "/agent-configs", json={"name": "c", "model": "m", "provider": "fake"}
        )
    ).json()["id"]
    await client.post("/skills/install", json={"name": "skill-creator"})
    # 不调用 PUT /skills(不启用)
    sid = (await client.post("/sessions", json={"agent_config_id": aid})).json()["id"]
    # FakeProvider 第一轮会尝试 read_file,读不到 → is_error;第二轮收尾。回合仍 200。
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "x"})
    assert r.status_code == 200, r.text
    assert not (base / str(uid) / "workspace" / ".skills").exists()
