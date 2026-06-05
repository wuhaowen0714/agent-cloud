from __future__ import annotations

from dataclasses import dataclass

from agent_cloud_common import (
    CompletionRequest,
    Message,
    Role,
    Usage,
)

from agent_cloud_worker.provider import Provider
from agent_cloud_worker.tools import ToolExecutor


@dataclass
class TurnResult:
    new_messages: list[Message]   # 本回合新增的 assistant/tool 消息(不含用户消息)
    usage: Usage
    stop_reason: str              # "end_turn" | "max_iterations"


async def run_turn(
    provider: Provider,
    executor: ToolExecutor,
    *,
    system: str,
    history: list[Message],
    user_message: str,
    max_iterations: int = 10,
) -> TurnResult:
    """跑一个回合:调 LLM → 有工具调用则执行并回填 → 直到无工具调用或达上限。

    用户消息由调用方(后端)单独持久化,因此不计入 new_messages。
    """
    working: list[Message] = [*history, Message(role=Role.USER, text=user_message)]
    new_messages: list[Message] = []
    usage = Usage()

    for _ in range(max_iterations):
        result = await provider.complete(
            CompletionRequest(system=system, messages=list(working), tools=executor.specs())
        )
        usage.input_tokens += result.usage.input_tokens
        usage.output_tokens += result.usage.output_tokens

        assistant = result.message
        working.append(assistant)
        new_messages.append(assistant)

        if not assistant.tool_calls:
            return TurnResult(new_messages=new_messages, usage=usage, stop_reason="end_turn")

        tool_results = [await executor.execute(call) for call in assistant.tool_calls]
        tool_message = Message(role=Role.TOOL, tool_results=tool_results)
        working.append(tool_message)
        new_messages.append(tool_message)

    return TurnResult(new_messages=new_messages, usage=usage, stop_reason="max_iterations")
