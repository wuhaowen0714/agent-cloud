import json

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
            events.append(json.loads(line[len("data:"):].strip()))
    return events


async def _make_session(client):
    uid = (await client.post("/users", json={"email": "s@example.com"})).json()["id"]
    aid = (
        await client.post(
            "/agent-configs",
            json={"user_id": uid, "name": "c", "model": "m", "provider": "p"},
        )
    ).json()["id"]
    return (
        await client.post("/sessions", json={"user_id": uid, "agent_config_id": aid})
    ).json()["id"]


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
