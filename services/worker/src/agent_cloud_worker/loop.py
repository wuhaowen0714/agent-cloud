from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from agent_cloud_common import (
    CompletionRequest,
    Message,
    Role,
    TextDelta,
    ThinkingDelta,
    ToolCallStarted,
    ToolResult,
    ToolResultEvent,
    TurnDone,
    TurnEvent,
    Usage,
)

from agent_cloud_worker.provider import (
    Provider,
    ProviderCompleted,
    ProviderTextDelta,
    ProviderThinkingDelta,
    StreamingProvider,
)
from agent_cloud_worker.tools import ToolExecutor

# 工具调用参数被单次输出上限(finish_reason=length)掐断时回灌的修复性错误:
# 不执行残缺参数,让模型在回合内自行用更小的负载重试(如分块写文件)。
_TRUNCATED_CALL_RESULT = (
    "[tool-call truncated] The arguments for this call were cut off because the "
    "response hit the per-request output token limit (finish_reason=length). "
    "Re-issue the call with a smaller payload — e.g. write the file in smaller "
    "chunks across multiple calls."
)
# 参数非法但并非截断(finish_reason ≠ length):别误导模型去"减小负载",如实说 JSON 坏了。
_MALFORMED_CALL_RESULT = (
    "[tool-call invalid] The arguments for this call were not valid JSON. "
    "Re-issue the call with well-formed JSON arguments."
)
# 连续这么多轮出现被截断的工具调用就熔断收尾:模型没有接受修复引导,
# 继续循环只会按 max_iterations 烧满每轮的输出预算。
_TRUNCATION_FUSE = 2


@dataclass
class TurnResult:
    new_messages: list[Message]  # 本回合新增的 assistant/tool 消息(不含用户消息)
    usage: Usage
    stop_reason: str  # "end_turn" | "max_iterations"
    context_tokens: int = 0  # 最后一次 LLM 调用的 input_tokens(真实上下文大小,供压缩判阈值)


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

    stop_reason 语义:
      - "end_turn":模型自然收尾(最后一条是不含 tool_call 的 assistant 消息),回合完整。
      - "max_iterations":达到迭代上限,**回合不完整**。此时 new_messages 可能以一条
        TOOL 消息结尾(上限恰好卡在执行完一轮工具、尚未拿到收尾 assistant 之时),
        即存在“悬空”的工具结果而没有对应的最终 assistant 回复。本函数不对这种情况做
        任何修补;是否丢弃 / 重试 / 截断由调用方(后端)按 best-effort 策略决定
        (spec §8/§10)。

    max_iterations 必须 >= 1;为 0 会是与“真正达到上限”无法区分的静默 no-op,故拒绝。
    """
    if max_iterations < 1:
        raise ValueError("max_iterations must be >= 1")

    working: list[Message] = [*history, Message(role=Role.USER, text=user_message)]
    new_messages: list[Message] = []
    usage = Usage()
    last_input = 0  # 最后一次调用的 input_tokens = 真实上下文大小(usage 是累加,不能用于压缩判阈)

    for _ in range(max_iterations):
        result = await provider.complete(
            CompletionRequest(system=system, messages=list(working), tools=executor.specs())
        )
        usage.input_tokens += result.usage.input_tokens
        usage.output_tokens += result.usage.output_tokens
        last_input = result.usage.input_tokens

        assistant = result.message
        working.append(assistant)
        new_messages.append(assistant)

        if not assistant.tool_calls:
            return TurnResult(
                new_messages=new_messages, usage=usage, stop_reason="end_turn",
                context_tokens=last_input,
            )

        tool_results = [await executor.execute(call) for call in assistant.tool_calls]
        tool_message = Message(role=Role.TOOL, tool_results=tool_results)
        working.append(tool_message)
        new_messages.append(tool_message)

    return TurnResult(
        new_messages=new_messages, usage=usage, stop_reason="max_iterations",
        context_tokens=last_input,
    )


async def run_turn_stream(
    provider: StreamingProvider,
    executor: ToolExecutor,
    *,
    system: str,
    history: list[Message],
    user_message: str,
    max_iterations: int = 10,
) -> AsyncIterator[TurnEvent]:
    """流式版回合:消费 provider.stream 转发增量、执行工具并 yield 事件,最后 yield TurnDone。

    TurnDone 携带本回合新增的 assistant/tool 消息(供后端持久化);用户消息不计入。
    stop_reason="max_iterations" 表示回合未完成(可能止于 tool 消息),由调用方决定丢弃/重试。
    """
    if max_iterations < 1:
        raise ValueError("max_iterations must be >= 1")

    working: list[Message] = [*history, Message(role=Role.USER, text=user_message)]
    new_messages: list[Message] = []
    usage = Usage()
    last_input = 0  # 最后一次调用的 input_tokens = 真实上下文大小(供压缩判阈值)
    truncated_streak = 0  # 连续含截断工具调用的轮数(熔断用)

    for _ in range(max_iterations):
        completed: ProviderCompleted | None = None
        async for event in provider.stream(
            CompletionRequest(system=system, messages=list(working), tools=executor.specs())
        ):
            if isinstance(event, ProviderTextDelta):
                yield TextDelta(text=event.text)
            elif isinstance(event, ProviderThinkingDelta):
                yield ThinkingDelta(text=event.text)
            elif isinstance(event, ProviderCompleted):
                completed = event
        if completed is None:
            raise RuntimeError("provider stream ended without a ProviderCompleted event")

        usage.input_tokens += completed.usage.input_tokens
        usage.output_tokens += completed.usage.output_tokens
        last_input = completed.usage.input_tokens
        assistant = completed.message
        working.append(assistant)
        new_messages.append(assistant)

        if not assistant.tool_calls:
            # 文本被单次输出上限掐断 → stop_reason="length",backend 据此给落库消息
            # 追加截断提示(用户可「继续」);否则正常 end_turn。
            yield TurnDone(
                new_messages=new_messages,
                usage=usage,
                stop_reason="length" if completed.length_truncated else "end_turn",
                context_tokens=last_input,
            )
            return

        truncated_streak = truncated_streak + 1 if completed.truncated_call_ids else 0
        repair_msg = (
            _TRUNCATED_CALL_RESULT if completed.length_truncated else _MALFORMED_CALL_RESULT
        )
        tool_results = []
        for call in assistant.tool_calls:
            yield ToolCallStarted(call_id=call.id, name=call.name, arguments=call.arguments)
            if call.id in completed.truncated_call_ids:
                # 参数被截断/非法:不执行,回灌修复性错误让模型在回合内自行重试
                result = ToolResult(call_id=call.id, content=repair_msg, is_error=True)
            else:
                result = await executor.execute(call)
            yield ToolResultEvent(
                call_id=result.call_id, content=result.content, is_error=result.is_error
            )
            tool_results.append(result)
        tool_message = Message(role=Role.TOOL, tool_results=tool_results)
        working.append(tool_message)
        new_messages.append(tool_message)

        if truncated_streak >= _TRUNCATION_FUSE:
            # 模型连续多轮发出被截断的调用(修复引导无效):熔断,以 length 收尾,
            # 避免按 max_iterations 把每轮 32k 输出预算烧满。
            yield TurnDone(
                new_messages=new_messages, usage=usage, stop_reason="length",
                context_tokens=last_input,
            )
            return

    yield TurnDone(
        new_messages=new_messages, usage=usage, stop_reason="max_iterations",
        context_tokens=last_input,
    )
