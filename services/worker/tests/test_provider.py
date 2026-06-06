import pytest
from agent_cloud_common import (
    CompletionRequest,
    CompletionResult,
    Message,
    Role,
    ToolCall,
    Usage,
)
from agent_cloud_worker.provider import (
    FakeProvider,
    ProviderCompleted,
    ProviderTextDelta,
)


def _result(text: str) -> CompletionResult:
    return CompletionResult(
        message=Message(role=Role.ASSISTANT, text=text),
        usage=Usage(input_tokens=1, output_tokens=1),
    )


async def test_fake_provider_returns_scripted_in_order():
    provider = FakeProvider([_result("a"), _result("b")])
    req = CompletionRequest(system="", messages=[], tools=[])
    r1 = await provider.complete(req)
    r2 = await provider.complete(req)
    assert r1.message.text == "a"
    assert r2.message.text == "b"


async def test_fake_provider_raises_when_exhausted():
    provider = FakeProvider([_result("only")])
    req = CompletionRequest(system="", messages=[], tools=[])
    await provider.complete(req)
    # 仍是 IndexError,但带上清晰的脚本耗尽信息
    with pytest.raises(IndexError, match="FakeProvider script exhausted after 1 calls"):
        await provider.complete(req)


def _completion(text: str) -> CompletionResult:
    return CompletionResult(
        message=Message(role=Role.ASSISTANT, text=text),
        usage=Usage(input_tokens=1, output_tokens=2),
    )


async def test_stream_yields_text_delta_then_completed():
    provider = FakeProvider([_completion("hi")])
    events = [e async for e in provider.stream(CompletionRequest(system="", messages=[], tools=[]))]
    assert isinstance(events[0], ProviderTextDelta) and events[0].text == "hi"
    assert isinstance(events[-1], ProviderCompleted)
    assert events[-1].message.text == "hi"
    assert events[-1].usage.output_tokens == 2


async def test_stream_tool_call_message_only_completed():
    provider = FakeProvider([CompletionResult(
        message=Message(role=Role.ASSISTANT,
                        tool_calls=[ToolCall(id="c1", name="bash", arguments={})]),
        usage=Usage())])
    events = [e async for e in provider.stream(CompletionRequest(system="", messages=[], tools=[]))]
    assert len(events) == 1 and isinstance(events[0], ProviderCompleted)
    assert events[0].message.tool_calls[0].name == "bash"
