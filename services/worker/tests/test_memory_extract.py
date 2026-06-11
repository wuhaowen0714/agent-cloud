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


async def test_reconcile_only_agent_changed_with_verbatim_echo_keeps_user():
    # 只有 agent 变、user 逐字 echo:user 不被提升、不写(MOVE 防御只在内容有差异时触发)
    p = FakeProvider([_result(_json(False, "- keep me", True, "- 名字:nana"))])
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


# ---- MOVE 防御(审查 M1):搬运一侧 changed 手滑 false 不能造成静默丢事实 ----


async def test_move_with_fumbled_agent_flag_promotes_to_changed():
    # user 删了(changed=true)、agent 加了但手滑 false:内容非空且有差异 → 提升为 changed
    p = FakeProvider([_result(_json(True, "", False, "- 名字:nana"))])
    user_mem, user_changed, agent_mem, agent_changed, _ = await reconcile_memory(
        p, user_current="- 用户叫我nana", agent_current="", messages=[], soft_max_chars=2000
    )
    assert user_changed is True and user_mem == ""
    assert agent_changed is True and agent_mem == "- 名字:nana"  # 加的一侧被救回


async def test_fumbled_flag_with_empty_output_does_not_wipe():
    # 另一侧 changed 但本侧输出为空("懒空"):不提升,echo 现值,防误清块
    p = FakeProvider([_result(_json(True, "- u2", False, ""))])
    _, _, agent_mem, agent_changed, _ = await reconcile_memory(
        p, user_current="- u1", agent_current="- keep", messages=[], soft_max_chars=2000
    )
    assert agent_changed is False and agent_mem == "- keep"


async def test_both_false_keeps_pure_echo_guard():
    # 两块都 false:即使模型 echo 走样也不信(纯 echo-guard 语义不变)
    p = FakeProvider([_result(_json(False, "- garbled", False, "- also garbled"))])
    user_mem, user_changed, agent_mem, agent_changed, _ = await reconcile_memory(
        p, user_current="- u", agent_current="- a", messages=[], soft_max_chars=2000
    )
    assert user_changed is False and user_mem == "- u"
    assert agent_changed is False and agent_mem == "- a"


# ---- 解析加固(审查 M3/L1):记忆内容含 ``` / 裸换行 / null 不致确定性失败 ----


async def test_parse_survives_code_fence_inside_memory_content():
    # 块内容里合法含 ```(remember 的代码段原样入块)——先整体解码,不被剥围栏切坏
    mem_with_fence = "- 部署命令:\\n```bash\\nmake deploy\\n```"
    p = FakeProvider([_result(_json(True, mem_with_fence, False, ""))])
    user_mem, user_changed, _, _, _ = await reconcile_memory(
        p, user_current="", agent_current="", messages=[], soft_max_chars=2000
    )
    assert user_changed is True and "make deploy" in user_mem


async def test_parse_tolerates_bare_newlines_in_string_values():
    # 弱模型多行 bullets 不转义 \n(strict JSON 拒收)→ strict=False 容忍
    raw = (
        '{"user_changed": true, "user_memory": "- a\n- b",'
        ' "agent_changed": false, "agent_memory": ""}'
    )
    p = FakeProvider([_result(raw)])
    user_mem, user_changed, _, _, _ = await reconcile_memory(
        p, user_current="", agent_current="", messages=[], soft_max_chars=2000
    )
    assert user_changed is True and "- b" in user_mem


async def test_parse_tolerates_null_memory_for_empty_block():
    raw = (
        '{"user_changed": false, "user_memory": null, "agent_changed": false, "agent_memory": null}'
    )
    p = FakeProvider([_result(raw)])
    user_mem, user_changed, agent_mem, agent_changed, _ = await reconcile_memory(
        p, user_current="- keep", agent_current="", messages=[], soft_max_chars=2000
    )
    assert user_changed is False and user_mem == "- keep"
    assert agent_changed is False and agent_mem == ""


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
