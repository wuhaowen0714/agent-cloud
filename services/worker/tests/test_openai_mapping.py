from types import SimpleNamespace

from agent_cloud_common import (
    CompletionRequest,
    Message,
    Role,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from agent_cloud_worker.openai_provider import (
    message_from_openai,
    to_openai_messages,
    to_openai_tools,
)


def test_to_openai_messages_includes_system_only_if_present():
    req = CompletionRequest(system="SYS", messages=[Message(role=Role.USER, text="hi")], tools=[])
    out = to_openai_messages(req)
    assert out[0] == {"role": "system", "content": "SYS"}
    assert out[1] == {"role": "user", "content": "hi"}

    req2 = CompletionRequest(system="", messages=[Message(role=Role.USER, text="hi")], tools=[])
    assert to_openai_messages(req2)[0] == {"role": "user", "content": "hi"}


def test_to_openai_messages_assistant_tool_calls_and_tool_results():
    msgs = [
        Message(
            role=Role.ASSISTANT,
            text="",
            tool_calls=[ToolCall(id="c1", name="bash", arguments={"command": "ls"})],
        ),
        Message(
            role=Role.TOOL,
            tool_results=[
                ToolResult(call_id="c1", content="file.txt", is_error=False),
            ],
        ),
    ]
    out = to_openai_messages(CompletionRequest(system="", messages=msgs, tools=[]))
    assert out[0]["role"] == "assistant"
    assert out[0]["tool_calls"][0]["id"] == "c1"
    assert out[0]["tool_calls"][0]["type"] == "function"
    assert out[0]["tool_calls"][0]["function"]["name"] == "bash"
    assert out[0]["tool_calls"][0]["function"]["arguments"] == '{"command": "ls"}'
    # tool 角色的每个 result 展开成一条 openai tool 消息
    assert out[1] == {"role": "tool", "tool_call_id": "c1", "content": "file.txt"}


def test_to_openai_tools():
    specs = [ToolSpec(name="bash", description="run", input_schema={"type": "object"})]
    out = to_openai_tools(specs)
    assert out == [
        {
            "type": "function",
            "function": {"name": "bash", "description": "run", "parameters": {"type": "object"}},
        }
    ]


def test_message_from_openai_text_only():
    om = SimpleNamespace(content="hello", tool_calls=None)
    m = message_from_openai(om)
    assert m.role == Role.ASSISTANT and m.text == "hello" and m.tool_calls == []


def test_message_from_openai_with_tool_calls_parses_json_arguments():
    om = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id="c1",
                function=SimpleNamespace(name="bash", arguments='{"command": "ls"}'),
            )
        ],
    )
    m = message_from_openai(om)
    assert m.text == ""
    assert m.tool_calls == [ToolCall(id="c1", name="bash", arguments={"command": "ls"})]


def test_assistant_empty_text_no_tool_calls_keeps_empty_string():
    # 无 tool_calls 时 content 必须是 ""(不能 null),否则回放历史里的空 assistant 会 400
    msgs = [Message(role=Role.ASSISTANT, text="")]
    out = to_openai_messages(CompletionRequest(system="", messages=msgs, tools=[]))
    assert out[0] == {"role": "assistant", "content": ""}


def test_assistant_empty_text_with_tool_calls_allows_null_content():
    msgs = [
        Message(
            role=Role.ASSISTANT, text="", tool_calls=[ToolCall(id="c1", name="bash", arguments={})]
        )
    ]
    out = to_openai_messages(CompletionRequest(system="", messages=msgs, tools=[]))
    assert out[0]["content"] is None


def test_tool_result_error_is_marked_in_content():
    msgs = [
        Message(
            role=Role.TOOL, tool_results=[ToolResult(call_id="c1", content="boom", is_error=True)]
        )
    ]
    out = to_openai_messages(CompletionRequest(system="", messages=msgs, tools=[]))
    assert out[0]["content"] == "[tool error] boom"


def test_message_from_openai_captures_reasoning_content():
    om = SimpleNamespace(content="hi", tool_calls=None, reasoning_content="because X")
    assert message_from_openai(om).reasoning == "because X"


def test_assistant_reasoning_is_passed_back():
    # 思考模式端点要求把发起工具调用那轮的 reasoning 回传
    msgs = [
        Message(
            role=Role.ASSISTANT,
            text="",
            reasoning="my thoughts",
            tool_calls=[ToolCall(id="c1", name="bash", arguments={})],
        )
    ]
    out = to_openai_messages(CompletionRequest(system="", messages=msgs, tools=[]))
    assert out[0]["reasoning_content"] == "my thoughts"


def test_assistant_without_reasoning_omits_field():
    msgs = [Message(role=Role.ASSISTANT, text="hi")]
    out = to_openai_messages(CompletionRequest(system="", messages=msgs, tools=[]))
    assert "reasoning_content" not in out[0]
