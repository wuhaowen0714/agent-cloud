from agent_cloud_backend.models.message import Message as OrmMessage
from agent_cloud_backend.turn.messages import common_to_content, orm_to_common
from agent_cloud_common import Message as CommonMessage
from agent_cloud_common import Role, ToolCall, ToolResult


def test_orm_to_common_assistant_with_tool_calls():
    orm = OrmMessage(session_id=None, seq=0, role="assistant",
                     content={"text": "hi",
                              "tool_calls": [{"id": "c1", "name": "bash",
                                              "arguments": {"command": "echo x"}}],
                              "tool_results": []})
    cm = orm_to_common(orm)
    assert cm.role == Role.ASSISTANT and cm.text == "hi"
    assert cm.tool_calls[0].name == "bash"
    assert cm.tool_calls[0].arguments == {"command": "echo x"}


def test_common_to_content_round_trip():
    cm = CommonMessage(role=Role.TOOL,
                       tool_results=[ToolResult(call_id="c1", content="out", is_error=False)])
    content = common_to_content(cm)
    assert content == {"text": "", "tool_calls": [],
                       "tool_results": [{"call_id": "c1", "content": "out", "is_error": False}]}
    # round trip through orm shape
    back = orm_to_common(OrmMessage(session_id=None, seq=0, role="tool", content=content))
    assert back.tool_results[0].call_id == "c1" and back.tool_results[0].is_error is False


def test_orm_to_common_tolerates_missing_keys():
    cm = orm_to_common(OrmMessage(session_id=None, seq=0, role="user", content={"text": "hello"}))
    assert cm.role == Role.USER and cm.text == "hello"
    assert cm.tool_calls == [] and cm.tool_results == []
