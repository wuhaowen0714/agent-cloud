import uuid

import pytest

from agent_cloud.v1 import worker_pb2


@pytest.fixture
def fake_worker(monkeypatch):
    """让端点不真正连 worker:返回脚本化的 RunTurnResponse。"""
    captured = {}

    async def _fake(worker_endpoint, request):
        captured["request"] = request
        return worker_pb2.RunTurnResponse(
            new_messages=[
                worker_pb2.Msg(role="assistant", text="", tool_calls=[
                    worker_pb2.ToolCall(id="c1", name="bash", arguments_json='{"command": "echo hi"}')]),
                worker_pb2.Msg(role="tool", tool_results=[
                    worker_pb2.ToolResult(call_id="c1", content="hi\n", is_error=False)]),
                worker_pb2.Msg(role="assistant", text="done"),
            ],
            input_tokens=5, output_tokens=7, stop_reason="end_turn",
        )

    from agent_cloud_backend.api import turn as turn_module
    monkeypatch.setattr(turn_module, "run_turn_via_worker", _fake)
    return captured


async def _make_session(client):
    uid = (await client.post("/users", json={"email": "t@example.com"})).json()["id"]
    aid = (await client.post("/agent-configs",
           json={"user_id": uid, "name": "c", "model": "m", "provider": "p"})).json()["id"]
    sid = (await client.post("/sessions", json={"user_id": uid, "agent_config_id": aid})).json()["id"]
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
    assert fake_worker["request"].work_subdir == f"sessions/{sid}"


async def test_turn_releases_lock_so_second_turn_works(client, fake_worker):
    sid = await _make_session(client)
    assert (await client.post(f"/sessions/{sid}/turn", json={"content": "one"})).status_code == 200
    assert (await client.post(f"/sessions/{sid}/turn", json={"content": "two"})).status_code == 200


async def test_turn_on_missing_session_404(client, fake_worker):
    r = await client.post(f"/sessions/{uuid.uuid4()}/turn", json={"content": "x"})
    assert r.status_code == 404
