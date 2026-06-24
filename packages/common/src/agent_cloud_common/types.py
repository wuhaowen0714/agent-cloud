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
    # 多模态:user 消息附带的图片(data_uri 字符串,如 "data:image/png;base64,...")。worker
    # 调 LLM 前由 turn_images 路径经沙箱读成 data_uri 填入(spec: image-understanding)。
    images: list[str] = field(default_factory=list)
    # 非空 = 此消息属于该 task 工具调用(call_id)派生的子 agent;空 = 主 agent。前端历史按它把子
    # 消息归到对应子 agent 卡;后端落库进 content JSONB(不占 DB 列)。
    parent_call_id: str = ""


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
    # 单次调用的输出上限覆盖(None = 用 provider 配置值)。小输出任务(如起标题)
    # 用它收紧,免得话痨/思考型模型为几个字烧大段输出。
    max_tokens: int | None = None


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
