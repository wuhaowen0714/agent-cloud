from agent_cloud_backend.models.message import Message as OrmMessage
from agent_cloud_backend.turn.messages import active_images, common_to_content, orm_to_common
from agent_cloud_common import Message as CommonMessage
from agent_cloud_common import Role, ToolResult


def test_orm_to_common_assistant_with_tool_calls():
    orm = OrmMessage(
        session_id=None,
        seq=0,
        role="assistant",
        content={
            "text": "hi",
            "tool_calls": [{"id": "c1", "name": "bash", "arguments": {"command": "echo x"}}],
            "tool_results": [],
        },
    )
    cm = orm_to_common(orm)
    assert cm.role == Role.ASSISTANT and cm.text == "hi"
    assert cm.tool_calls[0].name == "bash"
    assert cm.tool_calls[0].arguments == {"command": "echo x"}


def test_common_to_content_round_trip():
    cm = CommonMessage(
        role=Role.TOOL, tool_results=[ToolResult(call_id="c1", content="out", is_error=False)]
    )
    content = common_to_content(cm)
    assert content == {
        "text": "",
        "images": [],
        "tool_calls": [],
        "tool_results": [{"call_id": "c1", "content": "out", "is_error": False}],
        "parent_call_id": "",
    }
    # round trip through orm shape
    back = orm_to_common(OrmMessage(session_id=None, seq=0, role="tool", content=content))
    assert back.tool_results[0].call_id == "c1" and back.tool_results[0].is_error is False


def test_parent_call_id_round_trip_through_content():
    # 子 agent 消息的 parent_call_id 经 content JSONB 往返;主 agent/旧数据缺键 → 容错空串
    cm = CommonMessage(role=Role.ASSISTANT, text="子", parent_call_id="call_abc")
    content = common_to_content(cm)
    assert content["parent_call_id"] == "call_abc"
    back = orm_to_common(OrmMessage(session_id=None, seq=0, role="assistant", content=content))
    assert back.parent_call_id == "call_abc"
    legacy = orm_to_common(OrmMessage(session_id=None, seq=0, role="user", content={"text": "hi"}))
    assert legacy.parent_call_id == ""


def test_orm_to_common_tolerates_missing_keys():
    cm = orm_to_common(OrmMessage(session_id=None, seq=0, role="user", content={"text": "hello"}))
    assert cm.role == Role.USER and cm.text == "hello"
    assert cm.tool_calls == [] and cm.tool_results == []
    assert cm.images == []  # 缺 images 键 → 空列表


def test_images_round_trip_through_content():
    cm = CommonMessage(role=Role.USER, text="what is this?", images=["upload/cat.png"])
    content = common_to_content(cm)
    assert content["images"] == ["upload/cat.png"]
    back = orm_to_common(OrmMessage(session_id=None, seq=0, role="user", content=content))
    assert back.images == ["upload/cat.png"]


class _Hist:
    def __init__(self, role, content):
        self.role = role
        self.content = content


def test_active_images_prefers_current_turn():
    hist = [_Hist("user", {"images": ["old.png"]})]
    assert active_images(hist, ["new.png"]) == ["new.png"]


def test_active_images_falls_back_to_latest_history_user_image():
    hist = [
        _Hist("user", {"images": ["a.png"]}),
        _Hist("assistant", {"text": "x"}),
        _Hist("user", {"images": ["b.png"]}),
        _Hist("assistant", {"text": "y"}),
        _Hist("user", {"text": "follow-up, no new image"}),
    ]
    assert active_images(hist, []) == ["b.png"]  # 最近一条带图的 user(延续追问)


def test_active_images_empty_when_none_present():
    hist = [_Hist("user", {"text": "hi"}), _Hist("assistant", {"text": "hello"})]
    assert active_images(hist, []) == []
