import asyncio
import uuid

import grpc
import pytest
from agent_cloud.v1 import worker_pb2
from agent_cloud_backend.turn.messages import common_to_content as _real_common_to_content
from sqlalchemy import text as sa_text


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

    from agent_cloud_backend.api import turn as turn_module

    monkeypatch.setattr(turn_module, "run_turn_via_worker", _fake)
    return captured


async def _make_session(client):
    uid = (await client.post("/users", json={"email": "t@example.com"})).json()["id"]
    aid = (
        await client.post(
            "/agent-configs", json={"user_id": uid, "name": "c", "model": "m", "provider": "p"}
        )
    ).json()["id"]
    sid = (await client.post("/sessions", json={"user_id": uid, "agent_config_id": aid})).json()[
        "id"
    ]
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


async def test_turn_on_missing_session_404(client, fake_worker):
    r = await client.post(f"/sessions/{uuid.uuid4()}/turn", json={"content": "x"})
    assert r.status_code == 404


# --- C1: a mid-turn DB error must not brick the session in `running` ---


async def test_midturn_generic_error_releases_lock(client_noraise, fake_worker, monkeypatch):
    """A generic exception while persisting new messages -> 500, but the
    session lock must be released so a later turn succeeds."""
    client = client_noraise
    sid = await _make_session(client)

    from agent_cloud_backend.api import turn as turn_module

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
    from agent_cloud_backend.api import turn as turn_module

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


async def test_worker_failure_502_releases_lock(client, monkeypatch):
    """A gRPC worker failure -> 502, and the lock must be released so a
    subsequent normal turn succeeds."""
    from agent_cloud_backend.api import turn as turn_module

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
    assert r.status_code == 502, r.text

    # lock released: a subsequent normal turn works
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

    from agent_cloud_backend.api import turn as turn_module

    monkeypatch.setattr(turn_module, "run_turn_via_worker", _fake)
