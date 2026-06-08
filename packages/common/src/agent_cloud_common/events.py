from __future__ import annotations

from dataclasses import dataclass

from agent_cloud_common.types import Message, Usage


@dataclass
class TextDelta:
    text: str


@dataclass
class ThinkingDelta:
    text: str


@dataclass
class ToolCallStarted:
    call_id: str
    name: str
    arguments: dict


@dataclass
class ToolResultEvent:
    call_id: str
    content: str
    is_error: bool


@dataclass
class TurnDone:
    new_messages: list[Message]
    usage: Usage
    stop_reason: str  # "end_turn" | "max_iterations"
    context_tokens: int = 0  # 最后一次 LLM 调用的 input_tokens(真实上下文大小,供压缩判阈值)


TurnEvent = TextDelta | ThinkingDelta | ToolCallStarted | ToolResultEvent | TurnDone
