"""动态首字节超时的纯函数:payload 文本长度(排除图)+ 预算夹逼。"""

from agent_cloud_worker.ttft import TtftConfig, payload_text_len, ttft_budget

# 与生产默认一致,边界清晰
_CFG = TtftConfig(
    text_base=12.0,
    multimodal_base=25.0,
    chars_per_second=2000.0,
    length_cap=20.0,
    floor=10.0,
    ceil=45.0,
)


# ---- payload_text_len ----


def test_payload_len_plain_strings():
    msgs = [
        {"role": "system", "content": "SYSTEM"},  # 6
        {"role": "user", "content": "hello"},  # 5
    ]
    assert payload_text_len(msgs) == 11


def test_payload_len_skips_image_base64():
    # 多模态 content parts:只数 text,跳过 image_url 的(巨大)data_uri
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "看图"},  # 2
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/jpeg;base64," + "A" * 100000},
                },
            ],
        }
    ]
    assert payload_text_len(msgs) == 2  # 10 万字符的图被排除


def test_payload_len_counts_tool_calls():
    # assistant 的 tool_calls(name + arguments)是发出去的 payload,计入
    args = '{"command":"ls"}'
    msgs = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "bash", "arguments": args},
                }
            ],
        }
    ]
    assert payload_text_len(msgs) == len("bash") + len(args)


def test_payload_len_tool_role_content():
    msgs = [{"role": "tool", "tool_call_id": "c1", "content": "result text"}]
    assert payload_text_len(msgs) == len("result text")


# ---- ttft_budget ----


def test_budget_text_short():
    # 纯文本 L=12k → base 12 + 12000/2000=6 = 18s
    msgs = [{"role": "user", "content": "x" * 12000}]
    budget, chars = ttft_budget(msgs, has_images=False, cfg=_CFG)
    assert chars == 12000
    assert budget == 18.0


def test_budget_text_long_hits_length_cap():
    # 纯文本 L=60k → length_add = min(30, 20)=20(cap) → 12+20 = 32s
    msgs = [{"role": "user", "content": "x" * 60000}]
    budget, _ = ttft_budget(msgs, has_images=False, cfg=_CFG)
    assert budget == 32.0


def test_budget_multimodal_base():
    # 含图,文本 L=12k → base 25 + 6 = 31s(图字节不计入长度,但 has_images 抬基线)
    msgs = [{"role": "user", "content": "x" * 12000}]
    budget, _ = ttft_budget(msgs, has_images=True, cfg=_CFG)
    assert budget == 31.0


def test_budget_multimodal_long_hits_ceil():
    # 含图 L=60k → 25 + 20 = 45 = ceil
    msgs = [{"role": "user", "content": "x" * 60000}]
    budget, _ = ttft_budget(msgs, has_images=True, cfg=_CFG)
    assert budget == 45.0


def test_budget_clamps_to_floor():
    # base+add 低于 floor → 夹到 floor
    cfg = TtftConfig(
        text_base=5, multimodal_base=25, chars_per_second=2000,
        length_cap=20, floor=10, ceil=45,
    )
    budget, _ = ttft_budget([{"role": "user", "content": "hi"}], has_images=False, cfg=cfg)
    assert budget == 10.0  # 5 + ~0 → 夹到 floor 10


def test_budget_clamps_to_ceil():
    # base 已超 ceil → 夹到 ceil
    cfg = TtftConfig(
        text_base=100, multimodal_base=100, chars_per_second=2000,
        length_cap=20, floor=10, ceil=45,
    )
    budget, _ = ttft_budget([{"role": "user", "content": "hi"}], has_images=False, cfg=cfg)
    assert budget == 45.0
