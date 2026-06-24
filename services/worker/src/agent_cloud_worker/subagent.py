"""SubagentExecutor:主 agent 经 `task` 工具派生流式子 agent。

装饰器链最外层包它,inner 是完整工具链(不含 task)。子 agent 复用全部底层工具、共享 sandbox
工作区,但拿不到 task —— 深度封顶 1、不能再派生。子 agent 的流式事件经 emit 队列流回主
run_turn_stream(打上 subagent_id),最终输出回填为 task 的工具结果。详见
docs/superpowers/specs/2026-06-24-streaming-subagent-design.md。
"""

from __future__ import annotations

import asyncio

from agent_cloud_common import (
    Message,
    Role,
    SubagentDone,
    SubagentStarted,
    ToolCall,
    ToolResult,
    ToolSpec,
    TurnDone,
    Usage,
)

from agent_cloud_worker.loop import run_turn_stream
from agent_cloud_worker.provider import StreamingProvider
from agent_cloud_worker.tools import ToolExecutor

_TASK_SPEC = ToolSpec(
    name="task",
    description=(
        "Delegate a self-contained subtask to a fresh sub-agent. The sub-agent has the same "
        "tools as you and shares your working directory (it can see and modify your files). "
        "It works autonomously and returns its final summary. It cannot spawn further sub-agents."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Short label for the subtask."},
            "prompt": {
                "type": "string",
                "description": "Detailed instructions for the sub-agent.",
            },
        },
        "required": ["description", "prompt"],
    },
)

_SUBAGENT_SYSTEM = (
    "You are a sub-agent spawned by a parent agent to complete one focused subtask. You have "
    "the same tools as the parent and share its working directory (you can see and modify its "
    "files). You cannot spawn further sub-agents. Work autonomously; when finished, reply with "
    "a concise summary of the result/outputs for the parent — no pleasantries.\n\n"
    "Subtask: {description}"
)


def _last_assistant_text(messages: list[Message]) -> str:
    for m in reversed(messages):
        if m.role == Role.ASSISTANT and m.text:
            return m.text
    return ""


def subagent_enabled(enabled_tools: list[str]) -> bool:
    """空 enabled_tools = 全部(含 task);否则需显式列出 'task'。与其它工具开关一致。"""
    return not enabled_tools or "task" in enabled_tools


class SubagentExecutor:
    """装饰器层:暴露 `task` 工具,handler 跑嵌套 run_turn_stream(子 agent)并透传其事件到 emit。

    inner = 完整工具链(不含 task)。子 agent 用 inner → 复用全部工具、共享 sandbox,但拿不到
    task(深度封顶 1)。子 agent 事件经 self._emit 队列流回主 run_turn_stream(元素 (事件, sid))。
    """

    def __init__(
        self,
        inner: ToolExecutor,
        provider: StreamingProvider,
        emit: asyncio.Queue,
        *,
        max_iterations: int = 10,
    ) -> None:
        self._inner = inner
        self._provider = provider
        self._emit = emit
        self._max_iter = max_iterations
        self._n = 0
        self.accumulated_usage = Usage()

    def specs(self) -> list[ToolSpec]:
        return [*self._inner.specs(), _TASK_SPEC]

    async def execute(self, call: ToolCall) -> ToolResult:
        if call.name != "task":
            return await self._inner.execute(call)
        self._n += 1
        sid = f"sub-{self._n}"
        description = str(call.arguments.get("description", "")).strip()
        prompt = str(call.arguments.get("prompt", "")).strip()
        if not prompt:
            return ToolResult(call_id=call.id, content="task: 'prompt' is required", is_error=True)
        await self._emit.put((SubagentStarted(subagent_id=sid, description=description), sid))
        final, ok = "", True
        try:
            async for ev in run_turn_stream(
                self._provider,
                self._inner,
                system=_SUBAGENT_SYSTEM.format(description=description),
                history=[],
                user_message=prompt,
                max_iterations=self._max_iter,
                emit=None,  # 子 run_turn_stream 不再二级透传;其事件由本循环转发并打 sid
            ):
                if isinstance(ev, TurnDone):
                    final = _last_assistant_text(ev.new_messages)
                    self.accumulated_usage = Usage(
                        input_tokens=self.accumulated_usage.input_tokens + ev.usage.input_tokens,
                        output_tokens=self.accumulated_usage.output_tokens + ev.usage.output_tokens,
                    )
                else:
                    await self._emit.put((ev, sid))
        except Exception as exc:  # noqa: BLE001 — 子 agent 任意失败收敛为工具错误,不挂主回合
            ok = False
            final = f"sub-agent failed: {exc}"
        await self._emit.put((SubagentDone(subagent_id=sid, ok=ok), sid))
        return ToolResult(
            call_id=call.id,
            content=final or "(sub-agent produced no output)",
            is_error=not ok,
        )
