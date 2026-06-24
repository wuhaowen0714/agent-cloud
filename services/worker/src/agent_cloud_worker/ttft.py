"""动态首字节(TTFT)超时:按 payload 大小 + 是否多模态算 per-request 超时预算。

撞 sophnet 上游冷启时,流式请求的首字节迟迟不来。固定 45s 超时让纯文本短请求也要
卡满才重试;本模块按请求动态算预算,纯文本/短上下文快速 fail-fast 重试到 keepwarm
焐热的路由,多模态/长上下文给足不误杀。详见
docs/superpowers/specs/2026-06-24-dynamic-ttft-timeout-design.md。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TtftConfig:
    """动态首字节超时的参数,从 WorkerSettings 提取后注入 OpenAIProvider。"""

    text_base: float  # 纯文本基线(秒):路由热时连接 + 冷启判定余量
    multimodal_base: float  # 含图基线(秒):图编码首字节本就慢
    chars_per_second: float  # 长度加成:每这么多字符 +1s
    length_cap: float  # 长度加成封顶(秒)
    floor: float  # 预算下限(秒):防过激误杀
    ceil: float  # 预算上限(秒):取 = openai_timeout,最坏不比固定超时差


def payload_text_len(messages: list[dict]) -> int:
    """`to_openai_messages` 输出的总文本字符数,排除图片。

    content 为 str 直接计;为 list(多模态 content parts)时只数 type==text 的 text,
    跳过 image_url —— 其 base64 data_uri 不反映上游 prefill 难度,且体积巨大会扭曲长度。
    tool_calls 的 name + arguments 也是发出去的 payload,计入。
    """
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += len(part.get("text") or "")
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            total += len(fn.get("name") or "") + len(fn.get("arguments") or "")
    return total


def ttft_budget(
    messages: list[dict], has_images: bool, cfg: TtftConfig
) -> tuple[float, int]:
    """算首字节超时预算(秒)与 payload 字符数(供日志)。

    budget = clamp(base + 长度加成, floor, ceil);base 两档(纯文本 / 多模态),
    长度加成 = min(字符数 / chars_per_second, length_cap)。
    """
    char_len = payload_text_len(messages)
    base = cfg.multimodal_base if has_images else cfg.text_base
    length_add = min(char_len / cfg.chars_per_second, cfg.length_cap)
    budget = base + length_add
    return max(cfg.floor, min(budget, cfg.ceil)), char_len
