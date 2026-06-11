"""会话标题自动生成 e2e:两条 turn 路径成功收尾后,标题被异步填上;手动改名不被动。"""

import asyncio
import uuid

import pytest
import pytest_asyncio
from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.main import create_app
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.sandbox.deps import get_sandbox_manager
from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner
from agent_cloud_backend.sandbox.manager import SandboxManager
from agent_cloud_common import CompletionResult, Message, Role, Usage
from agent_cloud_worker.provider import FakeProvider
from agent_cloud_worker.server import create_server as create_worker_server
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker


def _say(text: str) -> CompletionResult:
    return CompletionResult(
        message=Message(role=Role.ASSISTANT, text=text),
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def _patch_global_sessionmaker(monkeypatch, engine):
    """标题钩子(与 runner 落库)经 db.get_sessionmaker() 走;指到测试引擎。"""
    import agent_cloud_backend.db as db_module

    monkeypatch.setattr(
        db_module, "_sessionmaker", async_sessionmaker(engine, expire_on_commit=False)
    )


def _make_stack(engine, tmp_path, scripted):
    """带定制 FakeProvider 脚本的全栈(真 worker + ASGI backend)。"""

    async def _build():
        provider = FakeProvider(scripted)
        worker_server, wport = await create_worker_server(
            provider_factory=lambda *a: provider, port=0
        )
        maker = async_sessionmaker(engine, expire_on_commit=False)

        async def _override_session():
            async with maker() as sdb:
                yield sdb

        provisioner = InProcessProvisioner(base_root=tmp_path)
        manager = SandboxManager(provisioner=provisioner, sessionmaker=maker)
        app = create_app()
        app.dependency_overrides[get_session] = _override_session
        app.dependency_overrides[get_settings] = lambda: Settings(
            worker_endpoint=f"localhost:{wport}"
        )
        app.dependency_overrides[get_sandbox_manager] = lambda: manager
        return app, worker_server, provisioner

    return _build


@pytest_asyncio.fixture
async def title_stack(engine, tmp_path, monkeypatch):
    _patch_global_sessionmaker(monkeypatch, engine)
    # 脚本:回合收尾文本 + 标题调用;第二个用例的会话已有标题,不消费标题脚本
    build = _make_stack(engine, tmp_path, [_say("收到,这就写"), _say("「快排实现」")])
    app, worker_server, provisioner = await build()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, engine
    await worker_server.stop(None)
    await provisioner.stop_all()


async def _register(client) -> str:
    reg = (
        await client.post(
            "/auth/register", json={"email": f"{uuid.uuid4()}@e.com", "password": "password123"}
        )
    ).json()
    client.headers["Authorization"] = f"Bearer {reg['access_token']}"
    return reg["user"]["id"]


async def _make_session(client, *, title: str | None = None) -> str:
    aid = (
        await client.post(
            "/agent-configs", json={"name": "coder", "model": "m", "provider": "fake"}
        )
    ).json()["id"]
    body = {"agent_config_id": aid}
    if title is not None:
        body["title"] = title
    return (await client.post("/sessions", json=body)).json()["id"]


async def _poll_title(engine, sid: str, *, timeout: float = 5.0) -> str | None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        async with maker() as db:
            title = (await db.get(Session, uuid.UUID(sid))).title
        if title is not None:
            return title
        await asyncio.sleep(0.05)
    return None


@pytest.mark.real_title
async def test_unary_turn_fills_title_async(title_stack):
    client, engine = title_stack
    await _register(client)
    sid = await _make_session(client)
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "帮我写一个快速排序"})
    assert r.status_code == 200, r.text
    # 标题是 fire-and-forget 异步任务:轮询直至落库(worker 清洗掉引号)
    assert await _poll_title(engine, sid) == "快排实现"


@pytest.mark.real_title
async def test_renamed_session_untouched(title_stack):
    client, engine = title_stack
    await _register(client)
    sid = await _make_session(client, title="我的名字")
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "随便聊聊"})
    assert r.status_code == 200, r.text
    await asyncio.sleep(0.2)  # 给(不该存在的)异步任务一点时间暴露问题
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        assert (await db.get(Session, uuid.UUID(sid))).title == "我的名字"


@pytest_asyncio.fixture
async def stream_title_stack(engine, tmp_path, monkeypatch):
    _patch_global_sessionmaker(monkeypatch, engine)
    build = _make_stack(engine, tmp_path, [_say("流式收到"), _say("流式标题")])
    app, worker_server, provisioner = await build()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, engine
    await worker_server.stop(None)
    await provisioner.stop_all()


@pytest.mark.real_title
async def test_stream_turn_fills_title_async(stream_title_stack):
    client, engine = stream_title_stack
    await _register(client)
    sid = await _make_session(client)
    async with client.stream(
        "POST", f"/sessions/{sid}/turn/stream", json={"content": "起个流式的名"}
    ) as r:
        assert r.status_code == 200
        async for _ in r.aiter_lines():
            pass  # 消费到流结束(turn_done 后 runner 收尾)
    assert await _poll_title(engine, sid) == "流式标题"
