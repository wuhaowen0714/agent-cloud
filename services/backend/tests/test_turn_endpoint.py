import asyncio
import uuid

import grpc
import pytest
from agent_cloud.v1 import worker_pb2
from agent_cloud_backend.turn.messages import common_to_content as _real_common_to_content
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import async_sessionmaker


def _patch_global_sessionmaker(monkeypatch, engine):
    """compaction 经 db.get_sessionmaker()(非 DI session)读写;指向测试引擎。"""
    import agent_cloud_backend.db as db_module

    monkeypatch.setattr(
        db_module, "_sessionmaker", async_sessionmaker(engine, expire_on_commit=False)
    )


async def _session_summary(engine, sid):
    from agent_cloud_backend.models.session import Session

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        stmt = (
            select(Session.summary)
            .where(Session.id == uuid.UUID(sid))
            .execution_options(populate_existing=True)
        )
        return (await db.execute(stmt)).scalar_one()


async def _seed_messages(engine, sid, n):
    from agent_cloud_backend.models.message import Message as M
    from agent_cloud_backend.repositories.message import MessageRepository

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        for i in range(n):
            await MessageRepository(db).append(
                uuid.UUID(sid),
                M(
                    session_id=uuid.UUID(sid),
                    seq=0,
                    role="user" if i % 2 == 0 else "assistant",
                    content={"text": f"m{i}", "tool_calls": [], "tool_results": []},
                ),
            )
        await db.commit()


@pytest.fixture
def fake_worker(monkeypatch):
    """让端点不真正连 worker:返回脚本化的 RunTurnResponse。"""
    captured = {}

    async def _fake(worker_endpoint, request):
        captured["request"] = request
        return worker_pb2.RunTurnResponse(
            new_messages=[
                worker_pb2.Msg(
                    role="assistant",
                    text="",
                    tool_calls=[
                        worker_pb2.ToolCall(
                            id="c1", name="bash", arguments_json='{"command": "echo hi"}'
                        )
                    ],
                ),
                worker_pb2.Msg(
                    role="tool",
                    tool_results=[
                        worker_pb2.ToolResult(call_id="c1", content="hi\n", is_error=False)
                    ],
                ),
                worker_pb2.Msg(role="assistant", text="done"),
            ],
            input_tokens=5,
            output_tokens=7,
            stop_reason="end_turn",
        )

    # 端点改薄后,worker 调用与消息转换移到 turn.headless;打桩目标随之指向 headless。
    from agent_cloud_backend.turn import headless as turn_module

    monkeypatch.setattr(turn_module, "run_turn_via_worker", _fake)
    return captured


async def _make_session(client):
    # 注册一个用户并把 access token 设为 client 默认 header,后续创建都归属本人。
    reg = await client.post(
        "/auth/register", json={"email": f"{uuid.uuid4()}@e.com", "password": "password123"}
    )
    client.headers["Authorization"] = f"Bearer {reg.json()['access_token']}"
    aid = (await client.post("/agent-configs", json={"name": "c"})).json()["id"]
    # model="m"(不在 model_context_windows 表 → 压缩阈值用全局默认,便于测试触发)
    sid = (
        await client.post("/sessions", json={"agent_config_id": aid, "model": "m"})
    ).json()["id"]
    return sid


async def test_turn_persists_and_returns(client, fake_worker):
    sid = await _make_session(client)
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "say hi"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stop_reason"] == "end_turn"
    assert [m["role"] for m in body["messages"]] == ["assistant", "tool", "assistant"]
    assert body["usage"]["output_tokens"] == 7
    # user message + 3 new persisted, in order
    listed = (await client.get(f"/sessions/{sid}/messages")).json()
    assert [m["role"] for m in listed] == ["user", "assistant", "tool", "assistant"]
    # assembled request carried the user message + work_subdir
    assert fake_worker["request"].user_message == "say hi"
    assert fake_worker["request"].work_subdir == "workspace"


async def test_turn_releases_lock_so_second_turn_works(client, fake_worker):
    sid = await _make_session(client)
    assert (await client.post(f"/sessions/{sid}/turn", json={"content": "one"})).status_code == 200
    assert (await client.post(f"/sessions/{sid}/turn", json={"content": "two"})).status_code == 200


async def test_turn_on_missing_session_404(auth_client, fake_worker):
    r = await auth_client.post(f"/sessions/{uuid.uuid4()}/turn", json={"content": "x"})
    assert r.status_code == 404


# --- C1: a mid-turn DB error must not brick the session in `running` ---


async def test_midturn_generic_error_releases_lock(client_noraise, fake_worker, monkeypatch):
    """A generic exception while persisting new messages -> 500, but the
    session lock must be released so a later turn succeeds."""
    client = client_noraise
    sid = await _make_session(client)

    # 端点改薄后,worker 调用与消息转换移到 turn.headless;打桩目标随之指向 headless。
    from agent_cloud_backend.turn import headless as turn_module

    def _boom(_message):
        raise RuntimeError("boom while converting message")

    monkeypatch.setattr(turn_module, "common_to_content", _boom)
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "one"})
    assert r.status_code == 500, r.text

    # lock released: a subsequent normal turn works
    monkeypatch.setattr(turn_module, "common_to_content", _real_common_to_content)
    r2 = await client.post(f"/sessions/{sid}/turn", json={"content": "two"})
    assert r2.status_code == 200, r2.text


async def test_midturn_aborted_tx_releases_lock(client_noraise, fake_worker, monkeypatch):
    """A real DB error that ABORTS the transaction during the NEW-message
    append -> 5xx, and the session must still be released. This is the key
    regression: release() must run on a clean tx, not the aborted one."""
    client = client_noraise
    from agent_cloud_backend.repositories.message import MessageRepository

    real_append = MessageRepository.append

    async def _failing_append(self, session_id, message):
        # let the user message through; abort the tx on the assistant/tool
        # messages with a non-integrity DB error (division by zero), which is
        # NOT mapped to 409 and leaves the transaction in an aborted state.
        if message.role != "user":
            await self.session.execute(sa_text("SELECT 1 / 0"))
        return await real_append(self, session_id, message)

    monkeypatch.setattr(MessageRepository, "append", _failing_append)
    sid = await _make_session(client)
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "one"})
    assert r.status_code >= 500, r.text

    # lock released despite the aborted tx: a later normal turn works
    monkeypatch.setattr(MessageRepository, "append", real_append)
    r2 = await client.post(f"/sessions/{sid}/turn", json={"content": "two"})
    assert r2.status_code == 200, r2.text


# --- Coverage backfill: concurrency + worker-failure lock release ---


async def test_concurrent_same_session_turns_one_200_one_409(client, monkeypatch):
    """Two overlapping turns on the same session: the lock serializes them,
    so exactly one gets 200 and the other 409."""
    # 端点改薄后,worker 调用与消息转换移到 turn.headless;打桩目标随之指向 headless。
    from agent_cloud_backend.turn import headless as turn_module

    async def _slow_worker(worker_endpoint, request):
        await asyncio.sleep(0.2)
        return worker_pb2.RunTurnResponse(
            new_messages=[worker_pb2.Msg(role="assistant", text="done")],
            input_tokens=1,
            output_tokens=1,
            stop_reason="end_turn",
        )

    monkeypatch.setattr(turn_module, "run_turn_via_worker", _slow_worker)
    sid = await _make_session(client)

    r1, r2 = await asyncio.gather(
        client.post(f"/sessions/{sid}/turn", json={"content": "a"}),
        client.post(f"/sessions/{sid}/turn", json={"content": "b"}),
    )
    assert {r1.status_code, r2.status_code} == {200, 409}, (r1.text, r2.text)


async def test_worker_unavailable_exhausts_to_503_releases_lock(client, monkeypatch):
    """瞬时 worker 失败重试耗尽 -> 503(可重试),且锁释放,后续回合成功。"""
    # 端点改薄后,worker 调用与消息转换移到 turn.headless;打桩目标随之指向 headless。
    from agent_cloud_backend.turn import headless as turn_module
    from agent_cloud_backend.turn import retry as retry_mod

    monkeypatch.setattr(retry_mod.RetryPolicy, "backoff_seconds", lambda self, i: 0.0)

    async def _failing_worker(worker_endpoint, request):
        raise grpc.aio.AioRpcError(
            code=grpc.StatusCode.UNAVAILABLE,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
            details="worker down",
        )

    monkeypatch.setattr(turn_module, "run_turn_via_worker", _failing_worker)
    sid = await _make_session(client)
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "one"})
    assert r.status_code == 503, r.text

    # lock released: a subsequent normal turn works
    monkeypatch.undo()
    _install_fake_worker(monkeypatch)
    r2 = await client.post(f"/sessions/{sid}/turn", json={"content": "two"})
    assert r2.status_code == 200, r2.text


async def test_worker_fatal_code_returns_502_releases_lock(client, monkeypatch):
    """非可恢复 gRPC code(fatal,如 INVALID_ARGUMENT)不重试 -> 502,锁释放。"""
    # 端点改薄后,worker 调用与消息转换移到 turn.headless;打桩目标随之指向 headless。
    from agent_cloud_backend.turn import headless as turn_module

    async def _failing_worker(worker_endpoint, request):
        raise grpc.aio.AioRpcError(
            code=grpc.StatusCode.INVALID_ARGUMENT,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
            details="bad request",
        )

    monkeypatch.setattr(turn_module, "run_turn_via_worker", _failing_worker)
    sid = await _make_session(client)
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "one"})
    assert r.status_code == 502, r.text

    monkeypatch.undo()
    _install_fake_worker(monkeypatch)
    r2 = await client.post(f"/sessions/{sid}/turn", json={"content": "two"})
    assert r2.status_code == 200, r2.text


def _install_fake_worker(monkeypatch):
    """Install a scripted worker after a previous monkeypatch.undo()."""

    async def _fake(worker_endpoint, request):
        return worker_pb2.RunTurnResponse(
            new_messages=[worker_pb2.Msg(role="assistant", text="done")],
            input_tokens=1,
            output_tokens=1,
            stop_reason="end_turn",
        )

    # 端点改薄后,worker 调用与消息转换移到 turn.headless;打桩目标随之指向 headless。
    from agent_cloud_backend.turn import headless as turn_module

    monkeypatch.setattr(turn_module, "run_turn_via_worker", _fake)


# --- Plan 12b: compaction (non-streaming endpoint) ---


async def test_turn_overflow_auto_retries_then_200(client, engine, monkeypatch):
    # 超窗一次 → force_compact 有进展 → 自动重试成功 → 200(用户无感)。
    _patch_global_sessionmaker(monkeypatch, engine)
    # 端点改薄后,worker 调用与消息转换移到 turn.headless;打桩目标随之指向 headless。
    from agent_cloud_backend.turn import headless as turn_module

    calls = {"n": 0}

    async def _worker(worker_endpoint, request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise grpc.aio.AioRpcError(
                code=grpc.StatusCode.RESOURCE_EXHAUSTED,
                initial_metadata=grpc.aio.Metadata(),
                trailing_metadata=grpc.aio.Metadata(),
            )
        return worker_pb2.RunTurnResponse(
            new_messages=[worker_pb2.Msg(role="assistant", text="done")],
            input_tokens=1, output_tokens=1, stop_reason="end_turn",
        )

    monkeypatch.setattr(turn_module, "run_turn_via_worker", _worker)

    async def _fake_summarize(endpoint, req):
        return "S"

    monkeypatch.setattr(
        "agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize
    )
    sid = await _make_session(client)
    await _seed_messages(engine, sid, 3)
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "go"})
    assert r.status_code == 200, r.text
    assert calls["n"] == 2  # 失败 1 + 重试 1


async def test_turn_transient_auto_retries_then_200(client, engine, monkeypatch):
    # 瞬时 UNAVAILABLE 一次 → 退避后自动重试成功 → 200。
    _patch_global_sessionmaker(monkeypatch, engine)
    # 端点改薄后,worker 调用与消息转换移到 turn.headless;打桩目标随之指向 headless。
    from agent_cloud_backend.turn import headless as turn_module
    from agent_cloud_backend.turn import retry as retry_mod

    monkeypatch.setattr(retry_mod.RetryPolicy, "backoff_seconds", lambda self, i: 0.0)
    calls = {"n": 0}

    async def _worker(worker_endpoint, request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise grpc.aio.AioRpcError(
                code=grpc.StatusCode.UNAVAILABLE,
                initial_metadata=grpc.aio.Metadata(),
                trailing_metadata=grpc.aio.Metadata(),
            )
        return worker_pb2.RunTurnResponse(
            new_messages=[worker_pb2.Msg(role="assistant", text="ok")],
            input_tokens=1, output_tokens=1, stop_reason="end_turn",
        )

    monkeypatch.setattr(turn_module, "run_turn_via_worker", _worker)
    sid = await _make_session(client)
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "go"})
    assert r.status_code == 200, r.text
    assert calls["n"] == 2


async def test_turn_transient_exhausted_returns_503(client, engine, monkeypatch):
    # 瞬时错误一直失败 → 退避重试耗尽 → 503(可重试)。
    _patch_global_sessionmaker(monkeypatch, engine)
    # 端点改薄后,worker 调用与消息转换移到 turn.headless;打桩目标随之指向 headless。
    from agent_cloud_backend.turn import headless as turn_module
    from agent_cloud_backend.turn import retry as retry_mod

    monkeypatch.setattr(retry_mod.RetryPolicy, "backoff_seconds", lambda self, i: 0.0)

    async def _worker(worker_endpoint, request):
        raise grpc.aio.AioRpcError(
            code=grpc.StatusCode.UNAVAILABLE,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
        )

    monkeypatch.setattr(turn_module, "run_turn_via_worker", _worker)
    sid = await _make_session(client)
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "go"})
    assert r.status_code == 503, r.text


async def test_turn_resource_exhausted_no_progress_returns_413(client, engine, monkeypatch):
    # RESOURCE_EXHAUSTED 但无历史可折叠(仅当前 user 消息)→ force-compact 无进展 → 413 不可重试。
    _patch_global_sessionmaker(monkeypatch, engine)
    # 端点改薄后,worker 调用与消息转换移到 turn.headless;打桩目标随之指向 headless。
    from agent_cloud_backend.turn import headless as turn_module

    async def _exhausted(worker_endpoint, request):
        raise grpc.aio.AioRpcError(
            code=grpc.StatusCode.RESOURCE_EXHAUSTED,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
            details="context window exceeded",
        )

    monkeypatch.setattr(turn_module, "run_turn_via_worker", _exhausted)

    called = {"n": 0}

    async def _fake_summarize(endpoint, req):
        called["n"] += 1
        return "S"

    monkeypatch.setattr(
        "agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize
    )

    sid = await _make_session(client)  # 不预置历史:只有本回合 user 消息
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "go"})
    assert r.status_code == 413, r.text
    assert called["n"] == 0  # 无可折叠,未调 summarize

    # 锁已释放:后续正常回合成功
    _install_fake_worker(monkeypatch)
    r2 = await client.post(f"/sessions/{sid}/turn", json={"content": "again"})
    assert r2.status_code == 200, r2.text


async def test_turn_post_compaction_when_over_threshold(client, engine, monkeypatch):
    # 回合后 context_tokens 超阈值 → 主动压缩,session.summary 被填。
    _patch_global_sessionmaker(monkeypatch, engine)
    monkeypatch.setenv("AGENT_CLOUD_COMPACTION_TOKEN_THRESHOLD", "10")
    monkeypatch.setenv("AGENT_CLOUD_COMPACTION_KEEP_RECENT", "2")
    # 端点改薄后,worker 调用与消息转换移到 turn.headless;打桩目标随之指向 headless。
    from agent_cloud_backend.turn import headless as turn_module

    async def _fake(worker_endpoint, request):
        # user + 3 新消息 = 4 条;keep_recent=2 → 折叠前 2
        return worker_pb2.RunTurnResponse(
            new_messages=[
                worker_pb2.Msg(role="assistant", text="a"),
                worker_pb2.Msg(role="assistant", text="b"),
                worker_pb2.Msg(role="assistant", text="done"),
            ],
            input_tokens=5,
            output_tokens=7,
            stop_reason="end_turn",
            context_tokens=999,
        )

    monkeypatch.setattr(turn_module, "run_turn_via_worker", _fake)

    async def _fake_summarize(endpoint, req):
        return "S"

    monkeypatch.setattr(
        "agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize
    )

    sid = await _make_session(client)
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "go"})
    assert r.status_code == 200, r.text
    assert await _session_summary(engine, sid) == "S"
