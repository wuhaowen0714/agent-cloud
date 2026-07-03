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


def test_to_openai_messages_user_with_images_builds_content_parts():
    # 多模态:user 带 images → content 为 parts 列表(text + image_url)。
    data_uri = "data:image/png;base64,AAAA"
    msgs = [Message(role=Role.USER, text="what is this?", images=[data_uri])]
    out = to_openai_messages(CompletionRequest(system="", messages=msgs, tools=[]))
    content = out[0]["content"]
    assert isinstance(content, list)
    assert {"type": "text", "text": "what is this?"} in content
    assert {"type": "image_url", "image_url": {"url": data_uri}} in content


def test_to_openai_messages_user_images_only_no_text():
    # 只有图无文本 → content 只含 image_url part(不放空 text part)。
    data_uri = "data:image/jpeg;base64,BBBB"
    msgs = [Message(role=Role.USER, text="", images=[data_uri])]
    out = to_openai_messages(CompletionRequest(system="", messages=msgs, tools=[]))
    assert out[0]["content"] == [{"type": "image_url", "image_url": {"url": data_uri}}]


def test_to_openai_messages_user_without_images_stays_plain_string():
    # 回归:无 images 的 user 仍是纯字符串 content(不影响现有文本路径)。
    out = to_openai_messages(
        CompletionRequest(system="", messages=[Message(role=Role.USER, text="hi")], tools=[])
    )
    assert out[0] == {"role": "user", "content": "hi"}


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
    # 配上合法发起者(裸 tool 消息属孤儿形态,会被 sanitize_tool_pairing 降级——那是 P1 的事,
    # 本测试只锁「失败标记折进 content」)。
    msgs = [
        Message(role=Role.ASSISTANT, text="", tool_calls=[ToolCall(id="c1", name="bash", arguments={})]),
        Message(
            role=Role.TOOL, tool_results=[ToolResult(call_id="c1", content="boom", is_error=True)]
        ),
    ]
    out = to_openai_messages(CompletionRequest(system="", messages=msgs, tools=[]))
    assert out[1]["content"] == "[tool error] boom"


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


# ---- P1: sanitize_tool_pairing(折叠边界切断配对的防御层)----

from agent_cloud_worker.openai_provider import sanitize_tool_pairing  # noqa: E402


def _tc(cid):
    return ToolCall(id=cid, name="bash", arguments={})


def _tr(cid, content="ok", is_error=False):
    return ToolResult(call_id=cid, content=content, is_error=is_error)


def test_sanitize_passthrough_when_properly_paired():
    msgs = [
        Message(role=Role.USER, text="do it"),
        Message(role=Role.ASSISTANT, text="", tool_calls=[_tc("c1")]),
        Message(role=Role.TOOL, tool_results=[_tr("c1")]),
        Message(role=Role.ASSISTANT, text="done"),
        Message(role=Role.USER, text="next"),
    ]
    out = sanitize_tool_pairing(msgs)
    assert out == msgs  # 正常配对零改动


def test_sanitize_orphan_tool_downgrades_to_user_text():
    # 折叠边界切断:开头就是孤儿 tool(发起者已折进摘要)→ 降级 user 文本,不再当协议消息
    msgs = [
        Message(role=Role.TOOL, tool_results=[_tr("gone", content="cmd output")]),
        Message(role=Role.ASSISTANT, text="continuing"),
        Message(role=Role.USER, text="next"),
    ]
    out = sanitize_tool_pairing(msgs)
    assert out[0].role == Role.USER
    assert "cmd output" in out[0].text and "[earlier tool result]" in out[0].text
    assert all(m.role != Role.TOOL for m in out)


def test_sanitize_orphan_error_result_keeps_error_mark():
    msgs = [Message(role=Role.TOOL, tool_results=[_tr("gone", content="boom", is_error=True)])]
    out = sanitize_tool_pairing(msgs)
    assert out[0].role == Role.USER and "(error)" in out[0].text


def test_sanitize_missing_result_gets_synthetic_tool_message():
    # assistant 发起了 c1,但结果被折走、下一条已是 user → 补合成结果,协议完整
    msgs = [
        Message(role=Role.ASSISTANT, text="", tool_calls=[_tc("c1")]),
        Message(role=Role.USER, text="next question"),
    ]
    out = sanitize_tool_pairing(msgs)
    assert [m.role for m in out] == [Role.ASSISTANT, Role.TOOL, Role.USER]
    assert out[1].tool_results[0].call_id == "c1"
    assert "folded away" in out[1].tool_results[0].content


def test_sanitize_trailing_dangling_assistant_gets_filled():
    # 折叠段以 assistant(tool_calls) 结尾(Summarize 请求可见此形态)→ 末尾补占位结果
    msgs = [
        Message(role=Role.USER, text="q"),
        Message(role=Role.ASSISTANT, text="", tool_calls=[_tc("c9")]),
    ]
    out = sanitize_tool_pairing(msgs)
    assert out[-1].role == Role.TOOL and out[-1].tool_results[0].call_id == "c9"


def test_sanitize_mixed_legit_and_orphan_results_in_one_message():
    # 同一条 tool 消息里 c1 合法、c2 孤儿 → 拆:合法走 tool,孤儿降级 user
    msgs = [
        Message(role=Role.ASSISTANT, text="", tool_calls=[_tc("c1")]),
        Message(role=Role.TOOL, tool_results=[_tr("c1"), _tr("c2", content="stray")]),
    ]
    out = sanitize_tool_pairing(msgs)
    roles = [m.role for m in out]
    assert roles == [Role.ASSISTANT, Role.TOOL, Role.USER]
    assert out[1].tool_results[0].call_id == "c1"
    assert "stray" in out[2].text


def test_to_openai_messages_never_emits_illegal_tool_sequence():
    # 集成:孤儿 tool 开头 + 缺结果 assistant → 输出序列里每条 role=tool 的 tool_call_id
    # 都能在紧邻其前的 assistant.tool_calls 里找到(严格端点不 400)
    msgs = [
        Message(role=Role.TOOL, tool_results=[_tr("gone")]),
        Message(role=Role.ASSISTANT, text="", tool_calls=[_tc("c1")]),
        Message(role=Role.USER, text="next"),
    ]
    out = to_openai_messages(CompletionRequest(system="s", messages=msgs, tools=[]))
    open_ids: set = set()
    for om in out:
        if om["role"] == "assistant":
            open_ids = {c["id"] for c in om.get("tool_calls", [])}
        elif om["role"] == "tool":
            assert om["tool_call_id"] in open_ids
        else:
            open_ids = set()


def test_sanitize_orphan_never_splits_a_multi_result_segment():
    # 审查低危 A 根治:assistant 发起 c1+c2,第一条 tool 带 c1 结果 + 一个孤儿,c2 结果在
    # 下一条 tool——孤儿降级的 user 必须等两条结果都放完再插,绝不夹在段中间。
    msgs = [
        Message(role=Role.ASSISTANT, text="", tool_calls=[_tc("c1"), _tc("c2")]),
        Message(role=Role.TOOL, tool_results=[_tr("c1"), _tr("stray", content="ghost")]),
        Message(role=Role.TOOL, tool_results=[_tr("c2")]),
        Message(role=Role.USER, text="next"),
    ]
    out = sanitize_tool_pairing(msgs)
    roles = [m.role for m in out]
    assert roles == [Role.ASSISTANT, Role.TOOL, Role.TOOL, Role.USER, Role.USER]
    assert out[1].tool_results[0].call_id == "c1"
    assert out[2].tool_results[0].call_id == "c2"
    assert "ghost" in out[3].text  # 孤儿排在段闭合之后
