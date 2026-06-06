import asyncio
import json

import grpc
import pytest
from agent_cloud_common import (
    Message,
    Role,
    TextDelta,
    ToolCallStarted,
    ToolResultEvent,
    TurnDone,
    Usage,
)
from agent_cloud_common.codec import turn_event_to_proto
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker


def _patch_global_sessionmaker(monkeypatch, engine):
    """The streaming proxy generator runs after the endpoint returns and opens a
    fresh session via ``db.get_sessionmaker()`` (not the request-scoped DI
    session). Point that module-global sessionmaker at the test engine so the
    ``turn_done`` persist and lock release hit the testcontainer DB."""
    import agent_cloud_backend.db as db_module

    monkeypatch.setattr(
        db_module, "_sessionmaker", async_sessionmaker(engine, expire_on_commit=False)
    )


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.strip().split("\n\n"):
        line = block.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:") :].strip()))
    return events


async def _make_session(client):
    uid = (await client.post("/users", json={"email": "s@example.com"})).json()["id"]
    aid = (
        await client.post(
            "/agent-configs",
            json={"user_id": uid, "name": "c", "model": "m", "provider": "p"},
        )
    ).json()["id"]
    return (await client.post("/sessions", json={"user_id": uid, "agent_config_id": aid})).json()[
        "id"
    ]


def _fake_stream(monkeypatch):
    async def _gen(worker_endpoint, request):
        events = [
            TextDelta(text="hel"),
            TextDelta(text="lo"),
            ToolCallStarted(call_id="c1", name="bash", arguments={"command": "echo hi"}),
            ToolResultEvent(call_id="c1", content="hi\n", is_error=False),
            TurnDone(
                new_messages=[
                    Message(role=Role.ASSISTANT, text="hello"),
                    Message(role=Role.TOOL),
                    Message(role=Role.ASSISTANT, text="done"),
                ],
                usage=Usage(input_tokens=5, output_tokens=7),
                stop_reason="end_turn",
            ),
        ]
        for e in events:
            yield turn_event_to_proto(e)

    from agent_cloud_backend.api import turn as turn_module

    monkeypatch.setattr(turn_module, "stream_turn_via_worker", _gen)


async def test_stream_endpoint_emits_events_and_persists(client, engine, monkeypatch):
    _patch_global_sessionmaker(monkeypatch, engine)
    _fake_stream(monkeypatch)
    sid = await _make_session(client)
    resp = await client.post(f"/sessions/{sid}/turn/stream", json={"content": "say hi"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    kinds = [e["type"] for e in events]
    assert kinds == ["text_delta", "text_delta", "tool_call_start", "tool_result", "turn_done"]
    done = events[-1]
    assert done["stop_reason"] == "end_turn" and len(done["message_ids"]) == 3
    assert done["usage"]["output_tokens"] == 7
    # persisted: user + 3 new
    listed = (await client.get(f"/sessions/{sid}/messages")).json()
    assert [m["role"] for m in listed] == ["user", "assistant", "tool", "assistant"]


async def test_stream_endpoint_releases_lock(client, engine, monkeypatch):
    _patch_global_sessionmaker(monkeypatch, engine)
    _fake_stream(monkeypatch)
    sid = await _make_session(client)
    resp = await client.post(f"/sessions/{sid}/turn/stream", json={"content": "one"})
    assert resp.status_code == 200
    # lock released -> a second stream works
    _fake_stream(monkeypatch)
    resp2 = await client.post(f"/sessions/{sid}/turn/stream", json={"content": "two"})
    assert resp2.status_code == 200


async def _make_session_row(engine):
    """Create user + agent_config + session directly via the test engine and
    return the session id, so unit tests can drive ``_sse_stream`` without the
    HTTP layer."""
    from agent_cloud_backend.models.agent_config import AgentConfig
    from agent_cloud_backend.models.user import User
    from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
    from agent_cloud_backend.repositories.session import SessionRepository
    from agent_cloud_backend.repositories.user import UserRepository

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        user = await UserRepository(db).create(User(email="c1@example.com"))
        await db.flush()
        agent = await AgentConfigRepository(db).create(
            AgentConfig(user_id=user.id, name="a", model="m", provider="p")
        )
        await db.flush()
        s = await SessionRepository(db).create_for(user.id, agent.id, None)
        await db.commit()
        return s.id


async def _read_status(engine, session_id) -> str:
    from agent_cloud_backend.models.session import Session

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        stmt = (
            select(Session.status)
            .where(Session.id == session_id)
            .execution_options(populate_existing=True)
        )
        return (await db.execute(stmt)).scalar_one()


async def test_sse_stream_releases_lock_on_client_disconnect(engine, monkeypatch):
    """C1 guard: a client disconnect cancels the task driving the SSE generator
    while it is suspended at a ``yield`` (the consumer is busy sending the
    previous chunk). The shielded ``finally`` cleanup must still release the
    session lock so ``status`` returns to ``idle`` instead of stranding at
    ``running`` until the 600s lease expires.

    NOTE: on the current runtime (CPython 3.13, asyncpg, SQLAlchemy 2.0) the
    un-shielded release already completes under every disconnect path I could
    construct, so this asserts the post-condition rather than reproducing a
    strict pre-fix failure. The ``asyncio.shield`` is defense-in-depth that
    guarantees release even if a future await sequence / Python version DOES
    re-deliver the cancellation into the cleanup's first await.
    """
    from agent_cloud_backend.api import turn as turn_module
    from agent_cloud_backend.repositories.session import SessionRepository

    _patch_global_sessionmaker(monkeypatch, engine)
    session_id = await _make_session_row(engine)

    # Acquire the lock first, mirroring what the endpoint does before streaming.
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        assert await SessionRepository(db).try_acquire(session_id) is True
        await db.commit()
    assert await _read_status(engine, session_id) == "running"

    # Worker yields events forever (a live stream the client abandons mid-flight).
    async def _stream(worker_endpoint, request):
        while True:
            yield turn_event_to_proto(TextDelta(text="hi"))
            await asyncio.sleep(0)

    monkeypatch.setattr(turn_module, "stream_turn_via_worker", _stream)

    gen = turn_module._sse_stream("ignored", object(), session_id)

    # Drive the generator from a task, mimicking Starlette's StreamingResponse:
    # ``async for chunk in body_iterator`` with an ``await`` between chunks (the
    # send over the wire). On disconnect that task is cancelled while the
    # generator is parked at a ``yield``.
    async def _drive():
        async for _chunk in gen:
            await asyncio.sleep(0.05)  # "sending" the chunk to the client

    task = asyncio.ensure_future(_drive())
    await asyncio.sleep(0.02)  # let the stream start (parked mid-send)
    task.cancel()  # client disconnects
    with pytest.raises(asyncio.CancelledError):
        await task

    # Ensure the generator's finally has fully run (close it if the cancellation
    # left it suspended), then pump the loop so the shielded cleanup completes.
    try:
        await gen.aclose()
    except asyncio.CancelledError:
        pass
    for _ in range(5):
        await asyncio.sleep(0)

    assert await _read_status(engine, session_id) == "idle"


def _fake_stream_then_turn_done(monkeypatch):
    """Fake worker stream: a couple text deltas then a TurnDone (the persist
    happens during the turn_done handling)."""

    async def _gen(worker_endpoint, request):
        yield turn_event_to_proto(TextDelta(text="hel"))
        yield turn_event_to_proto(TextDelta(text="lo"))
        yield turn_event_to_proto(
            TurnDone(
                new_messages=[Message(role=Role.ASSISTANT, text="hello")],
                usage=Usage(input_tokens=5, output_tokens=7),
                stop_reason="end_turn",
            )
        )

    from agent_cloud_backend.api import turn as turn_module

    monkeypatch.setattr(turn_module, "stream_turn_via_worker", _gen)


async def test_stream_endpoint_persist_error_emits_error_event_and_releases_lock(
    client, engine, monkeypatch
):
    """I1: a non-gRPC exception during the ``turn_done`` persist must surface as
    an in-band ``error`` event (not a silently truncated 200 stream), and the
    lock must still be released."""
    _patch_global_sessionmaker(monkeypatch, engine)
    _fake_stream_then_turn_done(monkeypatch)

    from agent_cloud_backend.api import turn as turn_module

    real_common_to_content = turn_module.common_to_content

    def _boom(common):
        raise RuntimeError("persist blew up")

    # common_to_content runs while building each message during the turn_done
    # persist -> raises a non-gRPC error inside the stream body.
    monkeypatch.setattr(turn_module, "common_to_content", _boom)

    sid = await _make_session(client)
    resp = await client.post(f"/sessions/{sid}/turn/stream", json={"content": "hi"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    # text deltas were already sent, then a terminal error event (not a cut-off)
    assert events[-1]["type"] == "error"
    assert events[-1]["recoverable"] is False
    assert [e["type"] for e in events[:2]] == ["text_delta", "text_delta"]

    # restore the converter; lock released -> a clean subsequent stream returns 200
    monkeypatch.setattr(turn_module, "common_to_content", real_common_to_content)
    _fake_stream(monkeypatch)
    resp2 = await client.post(f"/sessions/{sid}/turn/stream", json={"content": "again"})
    assert resp2.status_code == 200


# --- I2: abnormal-path regression coverage ---


def _fake_stream_grpc_error(monkeypatch):
    async def _gen(worker_endpoint, request):
        yield turn_event_to_proto(TextDelta(text="partial"))
        raise grpc.aio.AioRpcError(
            grpc.StatusCode.UNAVAILABLE,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
        )

    from agent_cloud_backend.api import turn as turn_module

    monkeypatch.setattr(turn_module, "stream_turn_via_worker", _gen)


async def test_stream_endpoint_worker_grpc_error_emits_recoverable_error_and_releases_lock(
    client, engine, monkeypatch
):
    """I2: a worker gRPC error mid-stream yields an in-band recoverable error
    event and releases the lock."""
    _patch_global_sessionmaker(monkeypatch, engine)
    _fake_stream_grpc_error(monkeypatch)
    sid = await _make_session(client)

    resp = await client.post(f"/sessions/{sid}/turn/stream", json={"content": "go"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[0]["type"] == "text_delta"
    assert events[-1]["type"] == "error"
    assert events[-1]["recoverable"] is True  # UNAVAILABLE is recoverable

    # lock released -> subsequent stream works
    _fake_stream(monkeypatch)
    resp2 = await client.post(f"/sessions/{sid}/turn/stream", json={"content": "retry"})
    assert resp2.status_code == 200


async def test_concurrent_same_session_streams_one_200_one_409(client, engine, monkeypatch):
    """I2: two concurrent streams on the same session -> exactly one acquires the
    lock (200) and the other is rejected (409)."""
    _patch_global_sessionmaker(monkeypatch, engine)

    async def _slow_gen(worker_endpoint, request):
        await asyncio.sleep(0.2)  # hold the lock long enough to overlap
        yield turn_event_to_proto(
            TurnDone(
                new_messages=[Message(role=Role.ASSISTANT, text="done")],
                usage=Usage(input_tokens=1, output_tokens=1),
                stop_reason="end_turn",
            )
        )

    from agent_cloud_backend.api import turn as turn_module

    monkeypatch.setattr(turn_module, "stream_turn_via_worker", _slow_gen)
    sid = await _make_session(client)

    r1, r2 = await asyncio.gather(
        client.post(f"/sessions/{sid}/turn/stream", json={"content": "a"}),
        client.post(f"/sessions/{sid}/turn/stream", json={"content": "b"}),
    )
    assert {r1.status_code, r2.status_code} == {200, 409}


async def test_preflight_assemble_failure_releases_lock(client_noraise, engine, monkeypatch):
    """I2: a failure during pre-flight request assembly (before streaming starts)
    must release the lock so the session is not stranded."""
    _patch_global_sessionmaker(monkeypatch, engine)

    from agent_cloud_backend.api import turn as turn_module

    real_assemble = turn_module.build_run_turn_request

    async def _boom(*args, **kwargs):
        raise RuntimeError("assemble failed")

    monkeypatch.setattr(turn_module, "build_run_turn_request", _boom)

    sid = await _make_session(client_noraise)
    resp = await client_noraise.post(f"/sessions/{sid}/turn/stream", json={"content": "x"})
    assert resp.status_code >= 500

    # restore assembly + a working worker stream; lock must have been released
    # by the pre-flight handler so a subsequent stream returns 200.
    monkeypatch.setattr(turn_module, "build_run_turn_request", real_assemble)
    _fake_stream(monkeypatch)
    resp2 = await client_noraise.post(f"/sessions/{sid}/turn/stream", json={"content": "y"})
    assert resp2.status_code == 200
