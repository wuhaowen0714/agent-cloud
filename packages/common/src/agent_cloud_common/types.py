from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    role: Role
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)   # assistant 用
    tool_results: list[ToolResult] = field(default_factory=list)  # tool 角色用
    # 思考模式的 reasoning_content。部分端点(如 DeepSeek 思考模式)要求:带 reasoning 的
    # assistant 回合(尤其发起工具调用那条)在回合内后续请求里必须把 reasoning 一并回传。
    reasoning: str = ""


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class CompletionRequest:
    system: str
    messages: list[Message]
    tools: list[ToolSpec]


@dataclass
class CompletionResult:
    message: Message
    usage: Usage


# ---- 上下文组装的输入(后端会在 2b 通过 run_turn 传入)----
@dataclass
class ContextDocument:
    scope: str  # "user" | "agent"
    type: str   # "USER" | "AGENTS" | ...
    content: str


@dataclass
class MemoryItem:
    scope: str  # "user" | "agent"
    content: str


@dataclass
class SkillRef:
    name: str
    description: str
    location: str
