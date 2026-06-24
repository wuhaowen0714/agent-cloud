"""SubagentExecutor:task 派生子 agent、透传事件、深度封顶、失败处理、usage 累加。"""

import asyncio

from agent_cloud_common import (
    CompletionResult,
    Message,
    Role,
    ToolCall,
    ToolResult,
    ToolSpec,
    Usage,
)
from agent_cloud_worker.provider import FakeProvider
from agent_cloud_worker.subagent import SubagentExecutor, subagent_enabled


class _InnerExec:
    """子 agent 的底层工具集(不含 task);记录被调用的工具名。"""

    def __init__(self):
        self.calls = []

    def specs(self):
        return [ToolSpec(name="read_file", description="d", input_schema={})]

    async def execute(self, call):
        self.calls.append(call.name)
        return ToolResult(call_id=call.id, content="文件内容", is_error=False)


def _sub_provider() -> FakeProvider:
    # 子 agent:第一轮读文件,第二轮收尾
    return FakeProvider(
        [
            CompletionResult(
                message=Message(
                    role=Role.ASSISTANT,
                    text="",
                    tool_calls=[ToolCall(id="r1", name="read_file", arguments={"path": "a"})],
                ),
                usage=Usage(input_tokens=2, output_tokens=1),
            ),
            CompletionResult(
                message=Message(role=Role.ASSISTANT, text="子结果:已读"),
                usage=Usage(input_tokens=3, output_tokens=2),
            ),
        ]
    )


def _drain(q):
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    return items


async def test_task_runs_subagent_and_returns_summary():
    q = asyncio.Queue()
    inner = _InnerExec()
    ex = SubagentExecutor(inner, _sub_provider(), q, max_iterations=5)
    result = await ex.execute(
        ToolCall(id="c1", name="task", arguments={"description": "读文件", "prompt": "读 a.txt"})
    )
    assert result.is_error is False and "子结果" in result.content
    items = _drain(q)
    kinds = [type(ev).__name__ for ev, _ in items]
    assert kinds[0] == "SubagentStarted" and kinds[-1] == "SubagentDone"
    assert all(sid == "sub-1" for _, sid in items)
    assert items[0][0].description == "读文件" and items[-1][0].ok is True
    assert "read_file" in inner.calls  # 子 agent 确实跑了底层工具


async def test_specs_exposes_task_but_inner_does_not():
    q = asyncio.Queue()
    inner = _InnerExec()
    ex = SubagentExecutor(inner, _sub_provider(), q)
    assert any(s.name == "task" for s in ex.specs())  # 主 agent 看得到 task
    assert not any(s.name == "task" for s in inner.specs())  # 子 agent(用 inner)看不到 → 封顶 1


async def test_non_task_delegates_to_inner():
    q = asyncio.Queue()
    inner = _InnerExec()
    ex = SubagentExecutor(inner, _sub_provider(), q)
    result = await ex.execute(ToolCall(id="x", name="read_file", arguments={"path": "a"}))
    assert result.content == "文件内容" and "read_file" in inner.calls


async def test_subagent_failure_returns_error_and_done_false():
    q = asyncio.Queue()
    # provider 脚本为空 → run_turn_stream 第一次 stream 抛 IndexError → 收敛为工具错误
    ex = SubagentExecutor(_InnerExec(), FakeProvider([]), q, max_iterations=5)
    result = await ex.execute(
        ToolCall(id="c1", name="task", arguments={"description": "x", "prompt": "go"})
    )
    assert result.is_error is True
    done = _drain(q)[-1][0]
    assert type(done).__name__ == "SubagentDone" and done.ok is False


async def test_missing_prompt_is_error_without_spawning():
    q = asyncio.Queue()
    ex = SubagentExecutor(_InnerExec(), _sub_provider(), q)
    result = await ex.execute(ToolCall(id="c1", name="task", arguments={"description": "x"}))
    assert result.is_error is True and "prompt" in result.content
    assert q.empty()  # 没派生 → 无事件


async def test_usage_accumulates():
    q = asyncio.Queue()
    ex = SubagentExecutor(_InnerExec(), _sub_provider(), q)
    await ex.execute(
        ToolCall(id="c1", name="task", arguments={"description": "x", "prompt": "go"})
    )
    # 子 agent 两轮:input 2+3=5、output 1+2=3
    assert ex.accumulated_usage.input_tokens == 5
    assert ex.accumulated_usage.output_tokens == 3


async def test_subagent_started_carries_prompt():
    # subagent_started 带上主 agent 给的完整 prompt(前端卡里展示)
    q = asyncio.Queue()
    ex = SubagentExecutor(_InnerExec(), _sub_provider(), q)
    await ex.execute(
        ToolCall(id="c1", name="task", arguments={"description": "读", "prompt": "读 a.txt 并总结"})
    )
    started = _drain(q)[0][0]
    assert type(started).__name__ == "SubagentStarted" and started.prompt == "读 a.txt 并总结"


async def test_accumulates_sub_messages_with_parent_call_id():
    # 子 agent 中间消息(assistant/tool)累积、每条标 parent_call_id=task call_id,供落库后重建过程
    q = asyncio.Queue()
    ex = SubagentExecutor(_InnerExec(), _sub_provider(), q, max_iterations=5)
    await ex.execute(
        ToolCall(id="call_xyz", name="task", arguments={"description": "x", "prompt": "go"})
    )
    subs = ex.accumulated_sub_messages
    assert len(subs) >= 2  # 子 agent:assistant(读)+ tool(结果)+ assistant(收尾)
    assert all(m.parent_call_id == "call_xyz" for m in subs)
    assert all(m.role != Role.USER for m in subs)  # user 不计入 new_messages(见 loop.py)


async def test_subagent_max_iterations_notes_incomplete():
    # 子 agent 每轮都发工具调用、不收尾 → 达 max_iterations → 结果带"未自然收尾"提示
    inner = _InnerExec()
    prov = FakeProvider(
        [
            CompletionResult(
                message=Message(
                    role=Role.ASSISTANT,
                    text="",
                    tool_calls=[ToolCall(id="t1", name="read_file", arguments={})],
                ),
                usage=Usage(),
            ),
            CompletionResult(
                message=Message(
                    role=Role.ASSISTANT,
                    text="",
                    tool_calls=[ToolCall(id="t2", name="read_file", arguments={})],
                ),
                usage=Usage(),
            ),
        ]
    )
    q = asyncio.Queue()
    ex = SubagentExecutor(inner, prov, q, max_iterations=2)
    result = await ex.execute(
        ToolCall(id="c1", name="task", arguments={"description": "x", "prompt": "go"})
    )
    assert result.is_error is False  # 达上限不算失败
    assert "incomplete" in result.content and "max_iterations" in result.content


def test_subagent_enabled_switch():
    assert subagent_enabled([]) is True  # 空 = 全部启用(含 task)
    assert subagent_enabled(["task"]) is True
    assert subagent_enabled(["bash", "read_file"]) is False  # 显式列表无 task → 不启用
