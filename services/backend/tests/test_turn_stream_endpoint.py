import asyncio
import json

import grpc
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
from sqlalchemy.ext.asyncio import async_sessionmaker


def _patch_global_sessionmaker(monkeypatch, engine):
    """The runner persists + releases via ``db.get_sessionmaker()`` (not the
    request-scoped DI session). Point that module-global sessionmaker at the test
    engine so the ``turn_done`` persist and lock release hit the testcontainer DB."""
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


def _set_worker_stream(monkeypatch, gen):
    """Patch the worker stream at its SOURCE module so the runner (which calls
    ``worker_client.stream_turn_via_worker``) sees the fake."""
    from agent_cloud_backend.turn import worker_client

    monkeypatch.setattr(worker_client, "stream_turn_via_worker", gen)


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

    _set_worker_stream(monkeypatch, _gen)


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


def _fake_stream_then_turn_done(monkeypatch):
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

    _set_worker_stream(monkeypatch, _gen)


async def test_stream_endpoint_persist_error_emits_error_event_and_releases_lock(
    client, engine, monkeypatch
):
    """A non-gRPC exception during the ``turn_done`` persist must surface as an
    in-band ``error`` event (not a silently truncated 200 stream), and the lock
    must still be released. The persist now runs in the runner -> patch its
    ``common_to_content``."""
    _patch_global_sessionmaker(monkeypatch, engine)
    _fake_stream_then_turn_done(monkeypatch)

    from agent_cloud_backend.turn import runner as runner_module

    real_c2c = runner_module.common_to_content

    def _boom(common):
        raise RuntimeError("persist blew up")

    monkeypatch.setattr(runner_module, "common_to_content", _boom)

    sid = await _make_session(client)
    resp = await client.post(f"/sessions/{sid}/turn/stream", json={"content": "hi"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    # text deltas were already sent, then a terminal error event (not a cut-off)
    assert events[-1]["type"] == "error"
    assert events[-1]["recoverable"] is False
    assert [e["type"] for e in events[:2]] == ["text_delta", "text_delta"]

    # restore the converter; lock released -> a clean subsequent stream returns 200
    monkeypatch.setattr(runner_module, "common_to_content", real_c2c)
    _fake_stream(monkeypatch)
    resp2 = await client.post(f"/sessions/{sid}/turn/stream", json={"content": "again"})
    assert resp2.status_code == 200


def _fake_stream_grpc_error(monkeypatch):
    async def _gen(worker_endpoint, request):
        yield turn_event_to_proto(TextDelta(text="partial"))
        raise grpc.aio.AioRpcError(
            grpc.StatusCode.UNAVAILABLE,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
        )

    _set_worker_stream(monkeypatch, _gen)


async def test_stream_endpoint_worker_grpc_error_emits_recoverable_error_and_releases_lock(
    client, engine, monkeypatch
):
    """A worker gRPC error mid-stream yields an in-band recoverable error event
    and releases the lock."""
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
    """Two concurrent streams on the same session -> exactly one acquires the lock
    (200) and the other is rejected (409)."""
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

    _set_worker_stream(monkeypatch, _slow_gen)
    sid = await _make_session(client)

    r1, r2 = await asyncio.gather(
        client.post(f"/sessions/{sid}/turn/stream", json={"content": "a"}),
        client.post(f"/sessions/{sid}/turn/stream", json={"content": "b"}),
    )
    assert {r1.status_code, r2.status_code} == {200, 409}


async def test_preflight_assemble_failure_releases_lock(client_noraise, engine, monkeypatch):
    """A failure during pre-flight request assembly (before streaming starts) must
    release the lock so the session is not stranded."""
    _patch_global_sessionmaker(monkeypatch, engine)

    from agent_cloud_backend.api import turn as turn_module

    real_assemble = turn_module.build_run_turn_request

    async def _boom(*args, **kwargs):
        raise RuntimeError("assemble failed")

    monkeypatch.setattr(turn_module, "build_run_turn_request", _boom)

    sid = await _make_session(client_noraise)
    resp = await client_noraise.post(f"/sessions/{sid}/turn/stream", json={"content": "x"})
    assert resp.status_code >= 500

    # restore assembly + a working worker stream; lock must have been released by
    # the pre-flight handler so a subsequent stream returns 200.
    monkeypatch.setattr(turn_module, "build_run_turn_request", real_assemble)
    _fake_stream(monkeypatch)
    resp2 = await client_noraise.post(f"/sessions/{sid}/turn/stream", json={"content": "y"})
    assert resp2.status_code == 200


# --- resume (GET) + cancel ---


async def test_get_resume_returns_204_when_no_active_turn(client, engine, monkeypatch):
    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session(client)
    r = await client.get(f"/sessions/{sid}/turn/stream")
    assert r.status_code == 204


async def test_get_resume_replays_active_turn(client, engine, monkeypatch):
    # 起一个慢回合,趁它在跑时用 GET 重连补播
    _patch_global_sessionmaker(monkeypatch, engine)

    async def _slow(worker_endpoint, request):
        yield turn_event_to_proto(TextDelta(text="hi"))
        await asyncio.sleep(0.3)
        yield turn_event_to_proto(
            TurnDone(
                new_messages=[Message(role=Role.ASSISTANT, text="done")],
                usage=Usage(input_tokens=1, output_tokens=1),
                stop_reason="end_turn",
            )
        )

    _set_worker_stream(monkeypatch, _slow)
    sid = await _make_session(client)
    post = asyncio.create_task(client.post(f"/sessions/{sid}/turn/stream", json={"content": "x"}))
    await asyncio.sleep(0.05)  # 让回合开始
    g = await client.get(f"/sessions/{sid}/turn/stream")
    assert g.status_code == 200
    assert "text_delta" in g.text
    await post


async def test_cancel_is_204_and_idempotent(client, engine, monkeypatch):
    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session(client)
    # 无在跑回合 → 幂等 204
    assert (await client.post(f"/sessions/{sid}/turn/cancel")).status_code == 204
