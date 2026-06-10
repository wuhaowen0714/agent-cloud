import pytest
from agent_cloud_common import (
    CompletionResult,
    Message,
    Role,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolCallProgress,
    ToolCallStarted,
    ToolResultEvent,
    TurnDone,
    Usage,
)
from agent_cloud_worker.loop import run_turn, run_turn_stream
from agent_cloud_worker.provider import (
    FakeProvider,
    ProviderCompleted,
    ProviderTextDelta,
    ProviderThinkingDelta,
    ProviderToolCallProgress,
)
from agent_cloud_worker.tools import LocalToolExecutor, builtin_tools


def _say(text: str) -> CompletionResult:
    return CompletionResult(
        message=Message(role=Role.ASSISTANT, text=text),
        usage=Usage(input_tokens=10, output_tokens=5),
    )


def _call(tool: str, args: dict, text: str = "") -> CompletionResult:
    return CompletionResult(
        message=Message(
            role=Role.ASSISTANT,
            text=text,
            tool_calls=[ToolCall(id="c1", name=tool, arguments=args)],
        ),
        usage=Usage(input_tokens=10, output_tokens=5),
    )


def _executor(tmp_path):
    return LocalToolExecutor(workdir=tmp_path, tools=builtin_tools())


async def test_single_response_no_tools(tmp_path):
    provider = FakeProvider([_say("final answer")])
    result = await run_turn(
        provider,
        _executor(tmp_path),
        system="",
        history=[],
        user_message="hi",
    )
    assert result.stop_reason == "end_turn"
    assert len(result.new_messages) == 1
    assert result.new_messages[0].role == Role.ASSISTANT
    assert result.new_messages[0].text == "final answer"
    # 不把用户消息算进 new_messages(后端单独持久化)
    assert all(m.role != Role.USER for m in result.new_messages)
    assert result.usage.output_tokens == 5


async def test_one_tool_round_then_finish(tmp_path):
    provider = FakeProvider(
        [
            _call("write_file", {"path": "out.txt", "content": "data"}),
            _say("done"),
        ]
    )
    result = await run_turn(
        provider,
        _executor(tmp_path),
        system="",
        history=[],
        user_message="write it",
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
    provider = FakeProvider(
        [
            _call("nope", {}),  # 未知工具 -> 错误结果回填
            _say("recovered"),
        ]
    )
    result = await run_turn(
        provider,
        _executor(tmp_path),
        system="",
        history=[],
        user_message="go",
    )
    assert result.stop_reason == "end_turn"
    assert result.new_messages[1].tool_results[0].is_error is True
    assert result.new_messages[-1].text == "recovered"


async def test_max_iterations_guard(tmp_path):
    # provider 永远返回工具调用,永不停止
    provider = FakeProvider([_call("bash", {"command": "echo x"}) for _ in range(10)])
    result = await run_turn(
        provider,
        _executor(tmp_path),
        system="",
        history=[],
        user_message="loop",
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

    history = [Message(role=Role.USER, text="earlier"), Message(role=Role.ASSISTANT, text="reply")]
    await run_turn(
        RecordingProvider(), _executor(tmp_path), system="SYS", history=history, user_message="now"
    )
    texts = [m.text for m in seen["messages"]]
    assert texts == ["earlier", "reply", "now"]


# ---- I3: max_iterations < 1 必须拒绝(否则是与真实达上限无法区分的静默 no-op) ----
async def test_max_iterations_zero_rejected(tmp_path):
    provider = FakeProvider([_say("never reached")])
    with pytest.raises(ValueError):
        await run_turn(
            provider,
            _executor(tmp_path),
            system="",
            history=[],
            user_message="hi",
            max_iterations=0,
        )


# ---- I2: 上限恰好卡在工具轮之后 → 回合不完整,new_messages 以 TOOL 结尾 ----
async def test_capped_mid_tool_ends_on_tool_message(tmp_path):
    calls = {"n": 0}

    class CountingProvider:
        async def complete(self, request):
            calls["n"] += 1
            return _call("bash", {"command": "echo x"})

    result = await run_turn(
        CountingProvider(),
        _executor(tmp_path),
        system="",
        history=[],
        user_message="loop",
        max_iterations=1,
    )
    assert result.stop_reason == "max_iterations"
    # 不完整回合:最后一条是工具结果消息,没有收尾的 assistant
    assert result.new_messages[-1].role == Role.TOOL
    assert len(result.new_messages) == 2  # 一个 assistant(含 tool_call) + 一个 tool 消息
    # provider 恰好被消费一次
    assert calls["n"] == 1


# ---- 覆盖补齐:单条 assistant 含多个 tool_call → 顺序执行并合并为一条 TOOL 消息 ----
async def test_multiple_tool_calls_in_one_message(tmp_path):
    multi = CompletionResult(
        message=Message(
            role=Role.ASSISTANT,
            tool_calls=[
                ToolCall(id="a", name="write_file", arguments={"path": "1.txt", "content": "one"}),
                ToolCall(id="b", name="write_file", arguments={"path": "2.txt", "content": "two"}),
                ToolCall(id="c", name="read_file", arguments={"path": "1.txt"}),
            ],
        ),
        usage=Usage(input_tokens=10, output_tokens=5),
    )
    provider = FakeProvider([multi, _say("done")])
    result = await run_turn(
        provider,
        _executor(tmp_path),
        system="",
        history=[],
        user_message="go",
    )
    assert result.stop_reason == "end_turn"
    assert [m.role for m in result.new_messages] == [Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]
    tool_msg = result.new_messages[1]
    # 三个工具结果合并进同一条 TOOL 消息,且保持调用顺序
    assert [r.call_id for r in tool_msg.tool_results] == ["a", "b", "c"]
    assert all(r.is_error is False for r in tool_msg.tool_results)
    assert tool_msg.tool_results[2].content == "one"  # read_file 读到先写入的内容
    assert (tmp_path / "1.txt").read_text() == "one"
    assert (tmp_path / "2.txt").read_text() == "two"


# ---- 覆盖补齐:history 不可变 —— 调用方传入的列表运行后不被修改 ----
async def test_history_list_not_mutated(tmp_path):
    history = [Message(role=Role.USER, text="earlier"), Message(role=Role.ASSISTANT, text="reply")]
    snapshot = list(history)
    provider = FakeProvider(
        [
            _call("write_file", {"path": "x.txt", "content": "d"}),
            _say("done"),
        ]
    )
    await run_turn(
        provider,
        _executor(tmp_path),
        system="",
        history=history,
        user_message="now",
    )
    # 调用方的 history 列表长度与内容均未变化
    assert history == snapshot
    assert len(history) == 2


# ---- 覆盖补齐:空 user_message 仍正常运行,provider 收到空文本的 USER 消息 ----
async def test_empty_user_message_runs(tmp_path):
    seen = {}

    class RecordingProvider:
        async def complete(self, request):
            seen["messages"] = request.messages
            return _say("ok")

    result = await run_turn(
        RecordingProvider(),
        _executor(tmp_path),
        system="",
        history=[],
        user_message="",
    )
    assert result.stop_reason == "end_turn"
    assert result.new_messages[-1].text == "ok"
    # provider 仍收到一条(空文本)USER 消息
    assert seen["messages"][-1].role == Role.USER
    assert seen["messages"][-1].text == ""


async def test_stream_single_response_no_tools(tmp_path):
    provider = FakeProvider([_say("hello")])
    events = [
        e
        async for e in run_turn_stream(
            provider, _executor(tmp_path), system="", history=[], user_message="hi"
        )
    ]
    assert isinstance(events[0], TextDelta) and events[0].text == "hello"
    assert isinstance(events[-1], TurnDone)
    assert events[-1].stop_reason == "end_turn"
    assert [m.role for m in events[-1].new_messages] == [Role.ASSISTANT]
    assert events[-1].usage.output_tokens == 5


async def test_stream_one_tool_round(tmp_path):
    provider = FakeProvider(
        [
            _call("write_file", {"path": "o.txt", "content": "data"}),
            _say("done"),
        ]
    )
    events = [
        e
        async for e in run_turn_stream(
            provider, _executor(tmp_path), system="", history=[], user_message="go"
        )
    ]
    kinds = [type(e).__name__ for e in events]
    assert "ToolCallStarted" in kinds and "ToolResultEvent" in kinds
    started = next(e for e in events if isinstance(e, ToolCallStarted))
    assert started.name == "write_file"
    tool_res = next(e for e in events if isinstance(e, ToolResultEvent))
    assert tool_res.is_error is False
    assert isinstance(events[-1], TurnDone) and events[-1].stop_reason == "end_turn"
    assert (tmp_path / "o.txt").read_text() == "data"
    assert [m.role for m in events[-1].new_messages] == [Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]
    assert events[-1].usage.output_tokens == 10  # 两轮累加


async def test_stream_max_iterations(tmp_path):
    provider = FakeProvider([_call("bash", {"command": "echo x"}) for _ in range(5)])
    events = [
        e
        async for e in run_turn_stream(
            provider,
            _executor(tmp_path),
            system="",
            history=[],
            user_message="loop",
            max_iterations=2,
        )
    ]
    assert isinstance(events[-1], TurnDone) and events[-1].stop_reason == "max_iterations"
    assert sum(isinstance(e, ToolResultEvent) for e in events) == 2


async def test_stream_rejects_zero_iterations(tmp_path):
    with pytest.raises(ValueError):
        async for _ in run_turn_stream(
            FakeProvider([]),
            _executor(tmp_path),
            system="",
            history=[],
            user_message="x",
            max_iterations=0,
        ):
            pass


# ---- M4 覆盖:provider 的 thinking 增量被转成 ThinkingDelta 事件 ----
async def test_stream_thinking_delta_forwarded(tmp_path):
    class ThinkingProvider:
        async def stream(self, request):
            yield ProviderThinkingDelta(text="hmm")
            yield ProviderTextDelta(text="ok")
            yield ProviderCompleted(
                message=Message(role=Role.ASSISTANT, text="ok"), usage=Usage()
            )

    events = [
        e
        async for e in run_turn_stream(
            ThinkingProvider(), _executor(tmp_path), system="", history=[], user_message="go"
        )
    ]
    # ThinkingDelta 先于 TextDelta 与 TurnDone
    assert isinstance(events[0], ThinkingDelta) and events[0].text == "hmm"
    kinds = [type(e).__name__ for e in events]
    assert kinds.index("ThinkingDelta") < kinds.index("TextDelta")
    assert kinds.index("TextDelta") < kinds.index("TurnDone")
    assert isinstance(events[-1], TurnDone) and events[-1].stop_reason == "end_turn"


async def test_context_tokens_is_last_call_input_not_sum(tmp_path):
    # 两次 LLM 调用:第一次带工具调用(input 100),第二次收尾(input 250)。
    # context_tokens 应 = 250(最后一次,真实上下文大小),usage.input_tokens = 350(累加)。
    provider = FakeProvider(
        [
            CompletionResult(
                message=Message(
                    role=Role.ASSISTANT,
                    tool_calls=[ToolCall(id="c1", name="bash", arguments={"command": "echo hi"})],
                ),
                usage=Usage(input_tokens=100, output_tokens=10),
            ),
            CompletionResult(
                message=Message(role=Role.ASSISTANT, text="done"),
                usage=Usage(input_tokens=250, output_tokens=20),
            ),
        ]
    )
    result = await run_turn(
        provider, _executor(tmp_path), system="", history=[], user_message="go"
    )
    assert result.usage.input_tokens == 350
    assert result.context_tokens == 250


# ---- finish_reason=length:截断处理(spec 2026-06-10-length-handling)----


class _ScriptedStreamProvider:
    """逐次调用返回脚本里的下一个 ProviderCompleted(可携带截断信息)。"""

    def __init__(self, completions):
        self._completions = list(completions)

    async def stream(self, request):
        completed = self._completions.pop(0)
        if completed.message.text:
            yield ProviderTextDelta(text=completed.message.text)
        yield completed


class _SpyExecutor:
    """记录被执行的 call;永远成功。"""

    def __init__(self):
        self.executed = []

    def specs(self):
        return []

    async def execute(self, call):
        from agent_cloud_common import ToolResult

        self.executed.append(call)
        return ToolResult(call_id=call.id, content="ok", is_error=False)


async def test_stream_truncated_tool_call_repairs_in_turn():
    truncated = ProviderCompleted(
        message=Message(
            role=Role.ASSISTANT,
            text="",
            tool_calls=[ToolCall(id="c1", name="write_file", arguments={})],
        ),
        usage=Usage(input_tokens=10, output_tokens=9),
        length_truncated=True,
        truncated_call_ids={"c1"},
    )
    final = ProviderCompleted(
        message=Message(role=Role.ASSISTANT, text="retried smaller, done"),
        usage=Usage(input_tokens=10, output_tokens=3),
    )
    executor = _SpyExecutor()
    events = [
        e
        async for e in run_turn_stream(
            _ScriptedStreamProvider([truncated, final]),
            executor,
            system="",
            history=[],
            user_message="write a huge file",
        )
    ]
    # 截断的 call 不进 executor
    assert executor.executed == []
    # 回灌修复性错误,模型在回合内重试
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert len(results) == 1
    assert results[0].is_error is True
    assert "tool-call truncated" in results[0].content
    # 回合最终正常收尾
    done = events[-1]
    assert isinstance(done, TurnDone)
    assert done.stop_reason == "end_turn"
    assert done.new_messages[-1].text == "retried smaller, done"


async def test_stream_text_truncation_surfaces_length_stop_reason():
    truncated = ProviderCompleted(
        message=Message(role=Role.ASSISTANT, text="half an ans"),
        usage=Usage(input_tokens=10, output_tokens=9),
        length_truncated=True,
    )
    events = [
        e
        async for e in run_turn_stream(
            _ScriptedStreamProvider([truncated]),
            _SpyExecutor(),
            system="",
            history=[],
            user_message="long essay please",
        )
    ]
    done = events[-1]
    assert isinstance(done, TurnDone)
    assert done.stop_reason == "length"
    assert done.new_messages[-1].text == "half an ans"


async def test_stream_truncation_fuse_ends_turn_after_two_rounds():
    # 连续两轮截断调用 → 熔断收尾(stop_reason="length"),不烧满 max_iterations
    def _trunc(call_id):
        return ProviderCompleted(
            message=Message(
                role=Role.ASSISTANT,
                text="",
                tool_calls=[ToolCall(id=call_id, name="write_file", arguments={})],
            ),
            usage=Usage(input_tokens=10, output_tokens=9),
            length_truncated=True,
            truncated_call_ids={call_id},
        )

    executor = _SpyExecutor()
    events = [
        e
        async for e in run_turn_stream(
            _ScriptedStreamProvider([_trunc("c1"), _trunc("c2"), _trunc("c3")]),
            executor,
            system="",
            history=[],
            user_message="huge write",
            max_iterations=10,
        )
    ]
    done = events[-1]
    assert isinstance(done, TurnDone)
    assert done.stop_reason == "length"
    assert executor.executed == []
    # 只消耗了两轮(熔断),脚本第三条没被取用
    assert sum(1 for e in events if isinstance(e, ToolResultEvent)) == 2


async def test_stream_malformed_args_get_invalid_message_not_truncated_wording():
    # 非 length 的坏 JSON:回灌「invalid」文案,不误导模型去减小负载
    bad = ProviderCompleted(
        message=Message(
            role=Role.ASSISTANT,
            text="",
            tool_calls=[ToolCall(id="c1", name="bash", arguments={})],
        ),
        usage=Usage(input_tokens=10, output_tokens=3),
        length_truncated=False,
        truncated_call_ids={"c1"},
    )
    final = ProviderCompleted(
        message=Message(role=Role.ASSISTANT, text="fixed"),
        usage=Usage(input_tokens=10, output_tokens=2),
    )
    events = [
        e
        async for e in run_turn_stream(
            _ScriptedStreamProvider([bad, final]),
            _SpyExecutor(),
            system="",
            history=[],
            user_message="go",
        )
    ]
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert "tool-call invalid" in results[0].content
    assert "token limit" not in results[0].content


async def test_stream_forwards_tool_progress(tmp_path):
    class _ProgressProvider:
        async def stream(self, request):
            yield ProviderToolCallProgress(
                call_id="c1", name="write_file", args_chars=120, lines=4, path_hint="a.py"
            )
            yield ProviderCompleted(
                message=Message(role=Role.ASSISTANT, text="done"),
                usage=Usage(input_tokens=1, output_tokens=1),
            )

    events = []
    async for e in run_turn_stream(
        _ProgressProvider(), _executor(tmp_path), system="", history=[], user_message="hi"
    ):
        events.append(e)
    prog = [e for e in events if isinstance(e, ToolCallProgress)]
    assert prog == [
        ToolCallProgress(call_id="c1", name="write_file", args_chars=120, lines=4, path_hint="a.py")
    ]
