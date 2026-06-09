from agent_cloud_common import CompletionResult, Message, Role, Usage

from agent_cloud_worker.memory_extract import reconcile_user_memory
from agent_cloud_worker.provider import FakeProvider


def _result(text: str) -> CompletionResult:
    return CompletionResult(
        message=Message(role=Role.ASSISTANT, text=text),
        usage=Usage(input_tokens=1, output_tokens=1),
    )


async def test_reconcile_adds():
    p = FakeProvider([_result('{"changed": true, "memory": "- prefers Python"}')])
    mem, changed, usage = await reconcile_user_memory(p, current="", messages=[], soft_max_chars=2000)
    assert changed is True
    assert "Python" in mem
    assert usage.input_tokens == 1


async def test_reconcile_noop_on_unparseable():
    p = FakeProvider([_result("not json at all")])
    mem, changed, _ = await reconcile_user_memory(
        p, current="- existing", messages=[], soft_max_chars=2000
    )
    assert mem == "- existing"  # 解析失败 → 不动现有块
    assert changed is False


async def test_reconcile_changed_false_echoes_current():
    p = FakeProvider([_result('{"changed": false, "memory": "- whatever"}')])
    mem, changed, _ = await reconcile_user_memory(
        p, current="- keep me", messages=[], soft_max_chars=2000
    )
    assert changed is False
    assert mem == "- keep me"


async def test_reconcile_strips_code_fence():
    p = FakeProvider([_result('```json\n{"changed": true, "memory": "- x"}\n```')])
    mem, changed, _ = await reconcile_user_memory(p, current="", messages=[], soft_max_chars=2000)
    assert changed is True
    assert mem.strip() == "- x"
