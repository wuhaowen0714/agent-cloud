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


def _delta(content=None, tool_calls=None, reasoning=None):
    d = SimpleNamespace(content=content, tool_calls=tool_calls, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(delta=d, finish_reason=None)], usage=None)


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
