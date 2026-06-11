import json

import pytest
from agent_cloud_common import CompletionResult, Message, Role, Usage
from agent_cloud_worker.memory_extract import MemoryParseError, reconcile_memory
from agent_cloud_worker.provider import FakeProvider


def _result(text: str) -> CompletionResult:
    return CompletionResult(
        message=Message(role=Role.ASSISTANT, text=text),
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def _json(user_changed, user_memory, agent_changed, agent_memory) -> str:
    return json.dumps(
        {
            "user_changed": user_changed,
            "user_memory": user_memory,
            "agent_changed": agent_changed,
            "agent_memory": agent_memory,
        }
    )


async def test_reconcile_updates_both_blocks():
    p = FakeProvider([_result(_json(True, "- prefers Python", True, "- my name is nana"))])
    user_mem, user_changed, agent_mem, agent_changed, usage = await reconcile_memory(
        p, user_current="", agent_current="", messages=[], soft_max_chars=2000
    )
    assert user_changed is True and "Python" in user_mem
    assert agent_changed is True and "nana" in agent_mem
    assert usage.input_tokens == 1


async def test_reconcile_only_agent_changed_echoes_user_current():
    # changed=false 的块必须回显【现值】而非模型 echo(模型可能漏抄/改写)
    p = FakeProvider([_result(_json(False, "- model garbled echo", True, "- 名字:nana"))])
    user_mem, user_changed, agent_mem, agent_changed, _ = await reconcile_memory(
        p, user_current="- keep me", agent_current="", messages=[], soft_max_chars=2000
    )
    assert user_changed is False and user_mem == "- keep me"
    assert agent_changed is True and "nana" in agent_mem


async def test_reconcile_raises_on_unparseable():
    # 解析失败必须抛(而非静默当 no-op)—— 否则后端会推进水位线、永久丢事实(C1)。
    p = FakeProvider([_result("not json at all")])
    with pytest.raises(MemoryParseError):
        await reconcile_memory(
            p, user_current="- existing", agent_current="", messages=[], soft_max_chars=2000
        )


async def test_reconcile_raises_on_missing_agent_keys():
    # 旧式单块输出(缺 agent_changed/agent_memory)不能被静默接受
    p = FakeProvider([_result('{"user_changed": true, "user_memory": "- x"}')])
    with pytest.raises(MemoryParseError):
        await reconcile_memory(
            p, user_current="", agent_current="", messages=[], soft_max_chars=2000
        )


async def test_reconcile_raises_on_mistyped_memory():
    p = FakeProvider([_result(_json(True, "- ok", True, 123))])
    with pytest.raises(MemoryParseError):
        await reconcile_memory(
            p, user_current="", agent_current="", messages=[], soft_max_chars=2000
        )


async def test_reconcile_tolerates_preamble_and_code_fence():
    p = FakeProvider([_result("Sure!\n```json\n" + _json(True, "- ok", False, "") + "\n```")])
    user_mem, user_changed, agent_mem, agent_changed, _ = await reconcile_memory(
        p, user_current="", agent_current="- mine", messages=[], soft_max_chars=2000
    )
    assert user_changed is True and user_mem.strip() == "- ok"
    assert agent_changed is False and agent_mem == "- mine"


async def test_prompt_carries_both_blocks_and_layer_rules():
    # 提炼 prompt 必须携带两块现值与分层判别(错层搬运的前提)
    p = FakeProvider([_result(_json(False, "", False, ""))])
    await reconcile_memory(
        p,
        user_current="- user fact",
        agent_current="- agent fact",
        messages=[Message(role=Role.USER, text="hi")],
        soft_max_chars=2000,
    )
    req = p.requests[0]
    assert "- user fact" in req.messages[0].text
    assert "- agent fact" in req.messages[0].text
    assert "OTHER agents" in req.system  # 判别句
    assert "MOVE" in req.system  # 错层事实搬运指令
