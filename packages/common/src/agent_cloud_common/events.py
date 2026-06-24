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
class ToolCallProgress:
    """工具调用参数生成中的节流进度(LLM 流式累积分片;不含参数内容本身)。"""

    call_id: str
    name: str
    args_chars: int
    lines: int
    path_hint: str


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


@dataclass
class SubagentStarted:
    """子 agent(task 工具)开始:包裹其事件区间起点。subagent_id 回合内唯一。"""

    subagent_id: str
    description: str


@dataclass
class SubagentDone:
    """子 agent 结束:ok=False 表示子 agent 抛错/未自然收尾。"""

    subagent_id: str
    ok: bool


TurnEvent = (
    TextDelta
    | ThinkingDelta
    | ToolCallProgress
    | ToolCallStarted
    | ToolResultEvent
    | TurnDone
    | SubagentStarted
    | SubagentDone
)
