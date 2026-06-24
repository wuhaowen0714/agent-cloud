"""run_turn_stream 的 emit 队列 drain:子 agent 事件穿插进主流(_Tagged)。"""

import asyncio

from agent_cloud_common import (
    CompletionResult,
    Message,
    Role,
    TextDelta,
    ToolCall,
    ToolResult,
    Usage,
)
from agent_cloud_worker.loop import _Tagged, run_turn_stream
from agent_cloud_worker.provider import FakeProvider


def _task_then_finish() -> FakeProvider:
    # 主 agent:第一轮发一个工具调用,第二轮收尾文本
    return FakeProvider(
        [
            CompletionResult(
                message=Message(
                    role=Role.ASSISTANT,
                    text="",
                    tool_calls=[ToolCall(id="c1", name="task", arguments={})],
                ),
                usage=Usage(input_tokens=1, output_tokens=1),
            ),
            CompletionResult(
                message=Message(role=Role.ASSISTANT, text="主结束"),
                usage=Usage(input_tokens=1, output_tokens=1),
            ),
        ]
    )


class _EmitExec:
    """执行工具时往 emit 队列 put 两个子事件,再返回结果。"""

    def __init__(self, emit):
        self._emit = emit

    def specs(self):
        return []

    async def execute(self, call):
        await self._emit.put((TextDelta(text="子a"), "sub-1"))
        await self._emit.put((TextDelta(text="子b"), "sub-1"))
        return ToolResult(call_id=call.id, content="done", is_error=False)


async def test_run_turn_stream_interleaves_subagent_events():
    q = asyncio.Queue()
    events = [
        e
        async for e in run_turn_stream(
            _task_then_finish(), _EmitExec(q), system="s", history=[], user_message="go", emit=q
        )
    ]
    tagged = [e for e in events if isinstance(e, _Tagged)]
    assert [t.event.text for t in tagged] == ["子a", "子b"]
    assert all(t.subagent_id == "sub-1" for t in tagged)
    # 子事件夹在 ToolCallStarted 与 ToolResultEvent 之间
    types = [type(e).__name__ for e in events]
    i_tagged = [i for i, e in enumerate(events) if isinstance(e, _Tagged)]
    assert types.index("ToolCallStarted") < min(i_tagged)
    assert max(i_tagged) < types.index("ToolResultEvent")


class _PlainExec:
    def specs(self):
        return []

    async def execute(self, call):
        return ToolResult(call_id=call.id, content="ok", is_error=False)


async def test_run_turn_stream_without_emit_has_no_tagged():
    events = [
        e
        async for e in run_turn_stream(
            _task_then_finish(), _PlainExec(), system="s", history=[], user_message="go"
        )
    ]
    assert not any(isinstance(e, _Tagged) for e in events)
