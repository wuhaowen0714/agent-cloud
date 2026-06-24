"""subagent 事件的 codec 往返 + subagent_id 外层透传。"""

from agent_cloud_common.codec import turn_event_from_proto, turn_event_to_proto
from agent_cloud_common.events import SubagentDone, SubagentStarted, TextDelta


def test_subagent_started_to_proto():
    p = turn_event_to_proto(SubagentStarted(subagent_id="sub-1", description="算个数"))
    assert p.WhichOneof("event") == "subagent_started"
    assert p.subagent_started.subagent_id == "sub-1"
    assert p.subagent_started.description == "算个数"


def test_subagent_done_to_proto():
    p = turn_event_to_proto(SubagentDone(subagent_id="sub-1", ok=False))
    assert p.subagent_done.subagent_id == "sub-1" and p.subagent_done.ok is False


def test_text_delta_carries_subagent_id():
    p = turn_event_to_proto(TextDelta(text="hi"), subagent_id="sub-1")
    assert p.subagent_id == "sub-1"
    assert p.text_delta.text == "hi"


def test_default_subagent_id_empty():
    assert turn_event_to_proto(TextDelta(text="hi")).subagent_id == ""


def test_subagent_started_roundtrip():
    ev = SubagentStarted(subagent_id="sub-2", description="读文件")
    back = turn_event_from_proto(turn_event_to_proto(ev))
    assert isinstance(back, SubagentStarted)
    assert back.subagent_id == "sub-2" and back.description == "读文件"


def test_subagent_done_roundtrip():
    back = turn_event_from_proto(turn_event_to_proto(SubagentDone(subagent_id="s", ok=True)))
    assert isinstance(back, SubagentDone) and back.ok is True
