from agent_cloud_common import (
    CompletionResult,
    Message,
    Role,
    ToolCall,
    Usage,
)
from agent_cloud_worker.loop import run_turn
from agent_cloud_worker.provider import FakeProvider
from agent_cloud_worker.tools import LocalToolExecutor, builtin_tools


def _say(text: str) -> CompletionResult:
    return CompletionResult(
        message=Message(role=Role.ASSISTANT, text=text),
        usage=Usage(input_tokens=10, output_tokens=5),
    )


def _call(tool: str, args: dict, text: str = "") -> CompletionResult:
    return CompletionResult(
        message=Message(role=Role.ASSISTANT, text=text,
                        tool_calls=[ToolCall(id="c1", name=tool, arguments=args)]),
        usage=Usage(input_tokens=10, output_tokens=5),
    )


def _executor(tmp_path):
    return LocalToolExecutor(workdir=tmp_path, tools=builtin_tools())


async def test_single_response_no_tools(tmp_path):
    provider = FakeProvider([_say("final answer")])
    result = await run_turn(
        provider, _executor(tmp_path),
        system="", history=[], user_message="hi",
    )
    assert result.stop_reason == "end_turn"
    assert len(result.new_messages) == 1
    assert result.new_messages[0].role == Role.ASSISTANT
    assert result.new_messages[0].text == "final answer"
    # 不把用户消息算进 new_messages(后端单独持久化)
    assert all(m.role != Role.USER for m in result.new_messages)
    assert result.usage.output_tokens == 5


async def test_one_tool_round_then_finish(tmp_path):
    provider = FakeProvider([
        _call("write_file", {"path": "out.txt", "content": "data"}),
        _say("done"),
    ])
    result = await run_turn(
        provider, _executor(tmp_path),
        system="", history=[], user_message="write it",
    )
    assert result.stop_reason == "end_turn"
    # assistant(含 tool_call) -> tool 结果消息 -> assistant(final)
    assert [m.role for m in result.new_messages] == [Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]
    assert (tmp_path / "out.txt").read_text() == "data"
    tool_msg = result.new_messages[1]
    assert tool_msg.tool_results[0].is_error is False
    # 两次 provider 调用的 usage 累加
    assert result.usage.output_tokens == 10


async def test_tool_error_feeds_back_and_continues(tmp_path):
    provider = FakeProvider([
        _call("nope", {}),     # 未知工具 -> 错误结果回填
        _say("recovered"),
    ])
    result = await run_turn(
        provider, _executor(tmp_path),
        system="", history=[], user_message="go",
    )
    assert result.stop_reason == "end_turn"
    assert result.new_messages[1].tool_results[0].is_error is True
    assert result.new_messages[-1].text == "recovered"


async def test_max_iterations_guard(tmp_path):
    # provider 永远返回工具调用,永不停止
    provider = FakeProvider([_call("bash", {"command": "echo x"}) for _ in range(10)])
    result = await run_turn(
        provider, _executor(tmp_path),
        system="", history=[], user_message="loop",
        max_iterations=3,
    )
    assert result.stop_reason == "max_iterations"
    # 3 轮 = 3 个 assistant + 3 个 tool 消息
    assert len(result.new_messages) == 6


async def test_history_is_preserved_in_request(tmp_path):
    # provider 校验它收到的 messages 含历史 + 新用户消息
    seen = {}

    class RecordingProvider:
        async def complete(self, request):
            seen["messages"] = request.messages
            return _say("ok")

    history = [Message(role=Role.USER, text="earlier"),
               Message(role=Role.ASSISTANT, text="reply")]
    await run_turn(RecordingProvider(), _executor(tmp_path),
                   system="SYS", history=history, user_message="now")
    texts = [m.text for m in seen["messages"]]
    assert texts == ["earlier", "reply", "now"]
