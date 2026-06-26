from types import SimpleNamespace

import httpx
import openai
import pytest
from agent_cloud_common import CompletionRequest, Message, Role, ToolSpec
from agent_cloud_worker.openai_provider import OpenAIProvider, _is_context_window_error
from agent_cloud_worker.provider import ContextWindowExceeded


class _FakeCompletions:
    def __init__(self, response=None, captured=None):
        self._response = response
        self._captured = captured if captured is not None else {}

    async def create(self, **kwargs):
        self._captured.update(kwargs)
        return self._response


def _client(response, captured=None):
    return SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions(response, captured)))


def _req(system="SYS", text="hi", tools=None):
    return CompletionRequest(
        system=system, messages=[Message(role=Role.USER, text=text)], tools=tools or []
    )


async def test_complete_text_only():
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello", tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3),
    )
    provider = OpenAIProvider(client=_client(resp), model="m", max_tokens=99)
    result = await provider.complete(_req())
    assert result.message.role == Role.ASSISTANT
    assert result.message.text == "hello"
    assert result.usage.input_tokens == 5 and result.usage.output_tokens == 3


async def test_complete_with_tool_call():
    resp = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="c1",
                            function=SimpleNamespace(name="bash", arguments='{"command": "ls"}'),
                        )
                    ],
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )
    provider = OpenAIProvider(client=_client(resp), model="m", max_tokens=99)
    result = await provider.complete(_req())
    assert result.message.tool_calls[0].name == "bash"
    assert result.message.tool_calls[0].arguments == {"command": "ls"}


async def test_complete_passes_model_tools_and_max_tokens():
    captured = {}
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="x", tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0),
    )
    provider = OpenAIProvider(client=_client(resp, captured), model="gpt-x", max_tokens=123)
    await provider.complete(_req(tools=[ToolSpec(name="bash", description="d", input_schema={})]))
    assert captured["model"] == "gpt-x"
    assert captured["max_tokens"] == 123
    assert captured["tools"][0]["function"]["name"] == "bash"
    assert "stream" not in captured or captured["stream"] is False


async def test_complete_omits_tools_when_empty():
    captured = {}
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="x", tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0),
    )
    provider = OpenAIProvider(client=_client(resp, captured), model="m", max_tokens=1)
    await provider.complete(_req(tools=[]))
    assert "tools" not in captured  # 空工具集不传 tools 键


from agent_cloud_worker.provider import (  # noqa: E402
    ProviderCompleted,
    ProviderTextDelta,
    ProviderThinkingDelta,
)


def _stream_client(chunks, captured=None):
    cap = captured if captured is not None else {}

    class _Comp:
        async def create(self, **kwargs):
            cap.update(kwargs)

            async def _gen():
                for c in chunks:
                    yield c

            return _gen()

    return SimpleNamespace(chat=SimpleNamespace(completions=_Comp()))


def _delta(content=None, tool_calls=None, reasoning=None, finish_reason=None):
    d = SimpleNamespace(content=content, tool_calls=tool_calls, reasoning_content=reasoning)
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=d, finish_reason=finish_reason)], usage=None
    )


def _usage_chunk(pt, ct):
    return SimpleNamespace(
        choices=[], usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct)
    )


async def test_stream_text_then_completed():
    chunks = [_delta(content="he"), _delta(content="llo"), _usage_chunk(5, 2)]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    texts = [e.text for e in events if isinstance(e, ProviderTextDelta)]
    assert texts == ["he", "llo"]
    done = events[-1]
    assert isinstance(done, ProviderCompleted)
    assert done.message.text == "hello"
    assert done.usage.input_tokens == 5 and done.usage.output_tokens == 2


async def test_stream_accumulates_tool_call_arguments():
    tc0 = SimpleNamespace(
        index=0, id="c1", function=SimpleNamespace(name="bash", arguments='{"comm')
    )
    tc1 = SimpleNamespace(
        index=0, id=None, function=SimpleNamespace(name=None, arguments='and": "ls"}')
    )
    chunks = [
        _delta(tool_calls=[tc0]),
        _delta(tool_calls=[tc1]),
        _usage_chunk(1, 1),
    ]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    done = events[-1]
    assert isinstance(done, ProviderCompleted)
    assert done.message.tool_calls[0].name == "bash"
    assert done.message.tool_calls[0].arguments == {"command": "ls"}


async def test_stream_maps_reasoning_content_to_thinking():
    chunks = [_delta(reasoning="thinking..."), _delta(content="answer"), _usage_chunk(1, 1)]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    assert any(isinstance(e, ProviderThinkingDelta) and e.text == "thinking..." for e in events)


async def test_complete_tolerates_missing_usage():
    # 部分 OpenAI 兼容端点非流式响应不带 usage;不应让成功的回合崩
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hi", tool_calls=None))],
        usage=None,
    )
    provider = OpenAIProvider(client=_client(resp), model="m", max_tokens=9)
    result = await provider.complete(_req())
    assert result.message.text == "hi"
    assert result.usage.input_tokens == 0 and result.usage.output_tokens == 0


async def test_complete_uses_configured_max_tokens_param():
    captured = {}
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="x", tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0),
    )
    provider = OpenAIProvider(
        client=_client(resp, captured),
        model="m",
        max_tokens=7,
        max_tokens_param="max_completion_tokens",
    )
    await provider.complete(_req())
    assert captured["max_completion_tokens"] == 7
    assert "max_tokens" not in captured


async def test_complete_captures_reasoning():
    resp = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="hi", tool_calls=None, reasoning_content="why")
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )
    provider = OpenAIProvider(client=_client(resp), model="m", max_tokens=9)
    result = await provider.complete(_req())
    assert result.message.reasoning == "why"


# ---- Plan 12a: 上下文超窗(上游 400)→ ContextWindowExceeded ----


def _bad_request(message, body=None):
    # 构造一个真实的 openai.BadRequestError(400),供检测逻辑测试
    req = httpx.Request("POST", "http://test")
    resp = httpx.Response(400, request=req)
    return openai.BadRequestError(message, response=resp, body=body)


def test_is_context_window_error_by_message():
    exc = _bad_request("This model's maximum context length is 8192 tokens, however ...")
    assert _is_context_window_error(exc) is True


def test_is_context_window_error_by_code():
    exc = _bad_request("generic message")
    exc.code = "context_length_exceeded"
    assert _is_context_window_error(exc) is True


def test_is_context_window_error_by_structured_body_code():
    # 真实上游:错误码嵌在 body.error.code,而 .code 属性为 None、message 仅 "Error code: 400"。
    # 这是最经典的 OpenAI 超窗形态 —— 必须能识别,否则会漏判。
    exc = _bad_request(
        "Error code: 400",
        body={"error": {"code": "context_length_exceeded", "message": "ctx too big"}},
    )
    assert _is_context_window_error(exc) is True


def test_is_context_window_error_by_structured_body_message():
    exc = _bad_request(
        "Error code: 400",
        body={"error": {"message": "This model's maximum context length is 8192 tokens"}},
    )
    assert _is_context_window_error(exc) is True


def test_is_context_window_error_false_for_other_400():
    assert _is_context_window_error(_bad_request("invalid value for 'temperature'")) is False


def test_is_context_window_error_false_for_param_too_long():
    # 守住 C1:某参数过长的无关 400,绝不能误判成超窗(否则后端会误触发压缩 → 压缩抖动)。
    exc = _bad_request(
        "Error code: 400",
        body={
            "error": {
                "code": "invalid_request_error",
                "message": "Invalid 'stop': string too long",
            }
        },
    )
    assert _is_context_window_error(exc) is False


def test_is_context_window_error_false_for_non_badrequest():
    assert _is_context_window_error(RuntimeError("boom")) is False


class _RaisingCompletions:
    def __init__(self, exc):
        self._exc = exc

    async def create(self, **kwargs):
        raise self._exc


def _raising_client(exc):
    return SimpleNamespace(chat=SimpleNamespace(completions=_RaisingCompletions(exc)))


async def test_complete_maps_context_overflow_to_context_window_exceeded():
    provider = OpenAIProvider(
        client=_raising_client(_bad_request("maximum context length exceeded")),
        model="m",
        max_tokens=9,
    )
    with pytest.raises(ContextWindowExceeded):
        await provider.complete(_req())


async def test_complete_reraises_unrelated_badrequest():
    provider = OpenAIProvider(
        client=_raising_client(_bad_request("invalid value for 'temperature'")),
        model="m",
        max_tokens=9,
    )
    with pytest.raises(openai.BadRequestError):
        await provider.complete(_req())


async def test_stream_maps_context_overflow_to_context_window_exceeded():
    provider = OpenAIProvider(
        client=_raising_client(_bad_request("This model's maximum context length is 8192 tokens")),
        model="m",
        max_tokens=9,
    )
    with pytest.raises(ContextWindowExceeded):
        async for _ in provider.stream(_req()):
            pass


async def test_stream_marks_length_truncation():
    chunks = [_delta(content="half answ"), _delta(finish_reason="length"), _usage_chunk(5, 9)]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    done = events[-1]
    assert isinstance(done, ProviderCompleted)
    assert done.length_truncated is True
    assert done.truncated_call_ids == set()


async def test_stream_tolerates_truncated_tool_call_args():
    # 参数 JSON 被 length 掐断:不抛 JSONDecodeError,降级为 {} 并报告 call id
    tc = SimpleNamespace(
        index=0, id="c1", function=SimpleNamespace(name="write_file", arguments='{"path": "a.t')
    )
    chunks = [_delta(tool_calls=[tc], finish_reason="length"), _usage_chunk(1, 9)]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    done = events[-1]
    assert isinstance(done, ProviderCompleted)
    assert done.length_truncated is True
    assert done.truncated_call_ids == {"c1"}
    call = done.message.tool_calls[0]
    assert call.id == "c1" and call.name == "write_file" and call.arguments == {}


async def test_stream_synthesizes_id_for_truncated_call_without_id():
    # 截断发生在 id 分片到达之前:合成 id(纯字母数字,兼容对 call_id 格式严格的端点)
    import re as _re

    tc = SimpleNamespace(index=0, id=None, function=SimpleNamespace(name="bash", arguments='{"co'))
    chunks = [_delta(tool_calls=[tc]), _usage_chunk(1, 9)]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    done = events[-1]
    call_id = done.message.tool_calls[0].id
    assert _re.fullmatch(r"trunc0[0-9a-f]{6}", call_id)
    assert done.truncated_call_ids == {call_id}


async def test_complete_tolerates_truncated_tool_call_args():
    # 一元路径止血:残缺参数不崩(降级 {}),不做回合内修复
    resp = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="c1",
                            function=SimpleNamespace(name="bash", arguments='{"comm'),
                        )
                    ],
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )
    provider = OpenAIProvider(client=_client(resp), model="m", max_tokens=9)
    result = await provider.complete(_req())
    assert result.message.tool_calls[0].arguments == {}


async def test_stream_accumulates_reasoning_into_message():
    chunks = [
        _delta(reasoning="th"),
        _delta(reasoning="ought"),
        _delta(content="answer"),
        _usage_chunk(1, 1),
    ]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    done = events[-1]
    assert done.message.reasoning == "thought"
    assert done.message.text == "answer"


# ---- completion 预算 ≥ 窗口的 400:配置错误,绝不能误判成超窗(审查 H1)----


def test_completion_budget_error_detected():
    from agent_cloud_worker.openai_provider import _is_completion_budget_error

    exc = _bad_request(
        "This model's maximum context length is 8192 tokens. However, you requested "
        "40000 tokens (7232 in the messages, 32768 in the completion). Please reduce "
        "the length of the messages or completion."
    )
    assert _is_completion_budget_error(exc) is True
    assert _is_context_window_error(exc) is True  # 文案同样命中超窗 markers → 判序必须预算优先


def test_prompt_dominant_overflow_stays_context_window():
    from agent_cloud_worker.openai_provider import _is_completion_budget_error

    # prompt 撑爆、completion 预算装得下:压缩有效 → 仍走超窗语义
    exc = _bad_request(
        "This model's maximum context length is 200000 tokens. However, you requested "
        "210000 tokens (177232 in the messages, 32768 in the completion)."
    )
    assert _is_completion_budget_error(exc) is False
    assert _is_context_window_error(exc) is True


async def test_stream_raises_completion_budget_exceeded():
    from agent_cloud_worker.provider import CompletionBudgetExceeded

    provider = OpenAIProvider(
        client=_raising_client(
            _bad_request(
                "maximum context length is 8192 tokens. However, you requested 40960 "
                "tokens (8192 in the messages, 32768 in the completion)."
            )
        ),
        model="m",
        max_tokens=32768,
    )
    with pytest.raises(CompletionBudgetExceeded):
        async for _ in provider.stream(_req()):
            pass


async def test_stream_length_with_empty_trailing_args_marked_truncated():
    # length 掐断且末尾 call 参数一个分片都没到:空 args 可"解析成功",但仍按截断处理
    tc = SimpleNamespace(index=0, id="c1", function=SimpleNamespace(name="bash", arguments=None))
    chunks = [_delta(tool_calls=[tc], finish_reason="length"), _usage_chunk(1, 9)]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    done = events[-1]
    assert done.truncated_call_ids == {"c1"}
    assert done.message.tool_calls[0].arguments == {}


# ---- 工具调用参数生成进度(节流发射) ----
from agent_cloud_worker import openai_provider as op_mod  # noqa: E402
from agent_cloud_worker.provider import ProviderToolCallProgress  # noqa: E402


def _tc(index=0, id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index, id=id, function=SimpleNamespace(name=name, arguments=arguments)
    )


def _fake_clock(monkeypatch, times):
    it = iter(times)
    monkeypatch.setattr(op_mod, "_monotonic", lambda: next(it))


async def test_stream_emits_throttled_tool_progress(monkeypatch):
    # 三个参数分片,时刻 10.0/10.1/10.5:首片立即发,间隔 0.1s 的不发,0.5s 的发
    _fake_clock(monkeypatch, [10.0, 10.1, 10.5])
    frag1 = '{"path": "a.py", "content": "x'
    chunks = [
        _delta(tool_calls=[_tc(id="c1", name="write_file", arguments=frag1)]),
        _delta(tool_calls=[_tc(arguments="yz")]),
        _delta(tool_calls=[_tc(arguments='123"}')]),
        _usage_chunk(1, 1),
    ]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    prog = [e for e in events if isinstance(e, ProviderToolCallProgress)]
    assert len(prog) == 2
    assert prog[0].call_id == "c1" and prog[0].name == "write_file"
    assert prog[0].path_hint == "a.py"
    assert prog[0].args_chars == len(frag1)
    assert prog[1].args_chars == len('{"path": "a.py", "content": "xyz123"}')
    # 进度事件不影响最终装配
    done = events[-1]
    assert isinstance(done, ProviderCompleted)
    assert done.message.tool_calls[0].arguments == {"path": "a.py", "content": "xyz123"}


async def test_stream_progress_waits_for_id(monkeypatch):
    # id/name 分片未到不发(孤儿进度无法与 ToolCallStarted 配对);到齐才发
    _fake_clock(monkeypatch, [10.0, 20.0])
    chunks = [
        _delta(tool_calls=[_tc(arguments='{"comm')]),
        _delta(tool_calls=[_tc(id="c1", name="bash", arguments='and": "ls"}')]),
        _usage_chunk(1, 1),
    ]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    prog = [e for e in events if isinstance(e, ProviderToolCallProgress)]
    assert len(prog) == 1
    assert prog[0].call_id == "c1" and prog[0].name == "bash"


async def test_stream_progress_path_arrives_across_fragments(monkeypatch):
    # path 值的闭引号晚到:此前 path_hint 为空,到齐后提取并缓存
    _fake_clock(monkeypatch, [10.0, 20.0, 30.0])
    chunks = [
        _delta(tool_calls=[_tc(id="c1", name="write_file", arguments='{"pa')]),
        _delta(tool_calls=[_tc(arguments='th": "src/m')]),
        _delta(tool_calls=[_tc(arguments='ain.py", "content": "')]),
        _usage_chunk(1, 1),
    ]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    prog = [e for e in events if isinstance(e, ProviderToolCallProgress)]
    assert [p.path_hint for p in prog] == ["", "", "src/main.py"]


async def test_stream_progress_decodes_escaped_path(monkeypatch):
    _fake_clock(monkeypatch, [10.0])
    chunks = [
        _delta(tool_calls=[_tc(id="c1", name="write_file",
                               arguments='{"path": "we\\"ird.py", "content": "')]),
        _usage_chunk(1, 1),
    ]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    prog = [e for e in events if isinstance(e, ProviderToolCallProgress)]
    assert prog[0].path_hint == 'we"ird.py'


async def test_stream_progress_counts_lines(monkeypatch):
    _fake_clock(monkeypatch, [10.0])
    chunks = [
        _delta(tool_calls=[_tc(id="c1", name="write_file",
                               arguments='{"path": "a", "content": "l1\\nl2\\nl3')]),
        _usage_chunk(1, 1),
    ]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    prog = [e for e in events if isinstance(e, ProviderToolCallProgress)]
    assert prog[0].lines == 3  # 两个 \n 转义 + 1


async def test_stream_text_only_emits_no_progress():
    chunks = [_delta(content="he"), _delta(content="llo"), _usage_chunk(1, 1)]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    assert not any(isinstance(e, ProviderToolCallProgress) for e in events)


def _fake_stall_clock(monkeypatch, times):
    it = iter(times)
    monkeypatch.setattr(op_mod, "_stall_monotonic", lambda: next(it))


async def test_stream_raises_on_upstream_stall(monkeypatch):
    # 上游持续发空 chunk(心跳/keep-alive)却不出 token:空转时钟跳过预算(ttft=None→60s 兜底)→
    # fail-fast(经 server 收敛为 INTERNAL,后端瞬时退避重试)。修"正在生成一直转"的根因。
    _fake_stall_clock(monkeypatch, [0.0, 1.0, 100.0])
    chunks = [_delta(), _delta()]  # 两个空 chunk(无 content/reasoning/tool)
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    with pytest.raises(RuntimeError, match="stalled"):
        async for _ in provider.stream(_req()):
            pass


async def test_stream_no_stall_while_producing(monkeypatch):
    # 即便空转时钟跳得很大,只要每个 chunk 有真实产出就刷新计时,正常长输出不被误杀。
    _fake_stall_clock(monkeypatch, [0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    chunks = [_delta(content="a"), _delta(content="b"), _usage_chunk(1, 1)]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    assert [e.text for e in events if isinstance(e, ProviderTextDelta)] == ["a", "b"]


# ---- 动态首字节(TTFT)超时:provider 按 payload 设 per-request timeout ----
from agent_cloud_worker.ttft import TtftConfig  # noqa: E402

_TTFT = TtftConfig(
    text_base=12.0, multimodal_base=25.0, chars_per_second=2000.0,
    length_cap=20.0, floor=10.0, ceil=45.0,
)


async def test_complete_does_not_set_ttft_timeout_even_with_config():
    # 非流式 complete 的 timeout 作用于整次生成,套 TTFT 会误杀正常长输出(如 RunTurn)→
    # 即便配了 ttft 也绝不设 per-request timeout,沿用 client 默认。TTFT 仅 stream 套。
    captured = {}
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="x", tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0),
    )
    provider = OpenAIProvider(client=_client(resp, captured), model="m", max_tokens=9, ttft=_TTFT)
    await provider.complete(_req(text="x" * 12000))
    assert "timeout" not in captured


async def test_stream_sets_ttft_timeout_from_payload():
    captured = {}
    chunks = [_delta(content="hi"), _usage_chunk(1, 1)]
    provider = OpenAIProvider(
        client=_stream_client(chunks, captured), model="m", max_tokens=9, ttft=_TTFT
    )
    async for _ in provider.stream(_req(text="x" * 12000)):
        pass
    assert captured["timeout"] == pytest.approx(12 + 12003 / 2000)


async def test_ttft_none_keeps_client_default_timeout():
    # 不传 ttft(向后兼容)→ 不设 per-request timeout,沿用 client 默认 45s
    captured = {}
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="x", tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0),
    )
    provider = OpenAIProvider(client=_client(resp, captured), model="m", max_tokens=9)
    await provider.complete(_req())
    assert "timeout" not in captured


async def test_ttft_multimodal_uses_higher_base_excluding_image_bytes():
    # 含图 → 用多模态基线(25)而非文本(12);图 base64 不计入长度
    captured = {}
    chunks = [_delta(content="hi"), _usage_chunk(1, 1)]
    provider = OpenAIProvider(
        client=_stream_client(chunks, captured), model="m", max_tokens=9, ttft=_TTFT
    )
    req = CompletionRequest(
        system="SYS",  # 3
        messages=[
            Message(
                role=Role.USER,
                text="看图",  # 2
                images=["data:image/jpeg;base64," + "Z" * 50000],
            )
        ],
        tools=[],
    )
    async for _ in provider.stream(req):
        pass
    assert captured["timeout"] == pytest.approx(25 + 5 / 2000)  # 图 5 万字节不计入
