import pytest
from agent_cloud.v1 import worker_pb2
from agent_cloud_common.codec import msg_from_proto, msg_to_proto
from agent_cloud_common.types import Message, Role, ToolCall, ToolResult


def test_round_trip_assistant_with_tool_calls():
    m = Message(role=Role.ASSISTANT, text="hi",
                tool_calls=[ToolCall(id="c1", name="bash", arguments={"command": "echo x"})])
    back = msg_from_proto(msg_to_proto(m))
    assert back.role == Role.ASSISTANT
    assert back.text == "hi"
    assert back.tool_calls[0].id == "c1"
    assert back.tool_calls[0].name == "bash"
    assert back.tool_calls[0].arguments == {"command": "echo x"}
    assert back.tool_results == []


def test_round_trip_tool_message():
    m = Message(role=Role.TOOL,
                tool_results=[ToolResult(call_id="c1", content="out", is_error=False),
                              ToolResult(call_id="c2", content="boom", is_error=True)])
    back = msg_from_proto(msg_to_proto(m))
    assert back.role == Role.TOOL
    assert [r.call_id for r in back.tool_results] == ["c1", "c2"]
    assert back.tool_results[1].is_error is True


def test_round_trip_plain_user():
    m = Message(role=Role.USER, text="hello")
    back = msg_from_proto(msg_to_proto(m))
    assert back.role == Role.USER and back.text == "hello"
    assert back.tool_calls == [] and back.tool_results == []


def test_from_proto_rejects_non_dict_arguments():
    # 防御:arguments_json 解析出来必须是 JSON object,否则 ToolCall.arguments 的类型契约被破坏。
    proto = worker_pb2.Msg(
        role="assistant",
        tool_calls=[worker_pb2.ToolCall(id="c1", name="bash", arguments_json="[]")],
    )
    with pytest.raises(ValueError, match="must be a JSON object"):
        msg_from_proto(proto)
