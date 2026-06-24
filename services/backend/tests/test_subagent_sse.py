"""subagent 事件 + subagent_id 透传到 SSE。"""

from agent_cloud_backend.turn.sse import turn_event_to_sse
from agent_cloud_common import SubagentDone, SubagentStarted, TextDelta


def test_text_delta_carries_subagent_id():
    d = turn_event_to_sse(TextDelta(text="hi"), subagent_id="sub-1")
    assert d == {"type": "text_delta", "text": "hi", "subagent_id": "sub-1"}


def test_no_subagent_id_key_when_empty():
    assert "subagent_id" not in turn_event_to_sse(TextDelta(text="hi"))


def test_subagent_started_maps():
    d = turn_event_to_sse(SubagentStarted(subagent_id="sub-1", description="读文件"), "sub-1")
    assert d["type"] == "subagent_started"
    assert d["subagent_id"] == "sub-1" and d["description"] == "读文件"


def test_subagent_done_maps():
    d = turn_event_to_sse(SubagentDone(subagent_id="sub-1", ok=True), "sub-1")
    assert d["type"] == "subagent_done" and d["ok"] is True
