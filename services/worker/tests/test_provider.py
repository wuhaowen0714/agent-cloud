import pytest
from agent_cloud_common import (
    CompletionRequest,
    CompletionResult,
    Message,
    Role,
    Usage,
)
from agent_cloud_worker.provider import FakeProvider


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
    with pytest.raises(IndexError):
        await provider.complete(req)
