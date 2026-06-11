"""会话标题生成:prompt 与输出清洗(GenerateTitle RPC 的纯逻辑部分)。"""

from __future__ import annotations

TITLE_SYSTEM = (
    "为下面这条用户消息起一个简短的会话标题。要求:不超过 16 个字;"
    "直接输出标题本身;不要引号、句号或任何解释。"
)

_QUOTES = [('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’"), ("「", "」"), ("『", "』")]


def clean_title(raw: str) -> str:
    """LLM 输出 → 可入库标题:压空白、剥成对引号、截 50 字符;清不出东西返回 ""。"""
    t = " ".join(raw.split())
    for left, right in _QUOTES:
        if len(t) >= 2 and t.startswith(left) and t.endswith(right):
            t = t[1:-1].strip()
    if len(t) > 50:
        t = t[:47] + "…"
    return t
