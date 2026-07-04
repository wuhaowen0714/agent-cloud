"""todo 任务清单工具(计划模式)测试。"""

from agent_cloud_common import ToolCall, ToolResult
from agent_cloud_worker.context import build_system_prompt
from agent_cloud_worker.todos import TodoExecutor, todo_enabled


class _Inner:
    def specs(self):
        return []

    async def execute(self, call):
        return ToolResult(call_id=call.id, content="inner", is_error=False)


def _call(items):
    return ToolCall(id="1", name="todo", arguments={"items": items})


def test_enabled_helper_and_specs_gating():
    assert todo_enabled([])  # 空 = 全部
    assert todo_enabled(["todo"])
    assert not todo_enabled(["bash"])
    on = {s.name for s in TodoExecutor(_Inner(), enabled=True).specs()}
    off = {s.name for s in TodoExecutor(_Inner(), enabled=False).specs()}
    assert "todo" in on and "todo" not in off


async def test_execute_counts_progress_and_names_current():
    ex = TodoExecutor(_Inner(), enabled=True)
    r = await ex.execute(_call([
        {"content": "查资料", "status": "completed"},
        {"content": "写初稿", "status": "in_progress"},
        {"content": "排版导出", "status": "pending"},
    ]))
    assert not r.is_error
    assert "1/3" in r.content and "写初稿" in r.content


async def test_execute_all_pending_is_a_plan():
    ex = TodoExecutor(_Inner(), enabled=True)
    r = await ex.execute(_call([
        {"content": "a", "status": "pending"},
        {"content": "b", "status": "pending"},
    ]))
    assert not r.is_error and "0/2" in r.content


async def test_execute_validates_items():
    ex = TodoExecutor(_Inner(), enabled=True)
    assert (await ex.execute(ToolCall(id="1", name="todo", arguments={}))).is_error
    assert (await ex.execute(_call([]))).is_error
    assert (await ex.execute(_call(["not-an-object"]))).is_error
    assert (await ex.execute(_call([{"content": "", "status": "pending"}]))).is_error
    assert (await ex.execute(_call([{"content": "x", "status": "done"}]))).is_error


async def test_disabled_rejects_and_passthrough():
    ex = TodoExecutor(_Inner(), enabled=False)
    r = await ex.execute(_call([{"content": "x", "status": "pending"}]))
    assert r.is_error
    passed = await ex.execute(ToolCall(id="2", name="bash", arguments={}))
    assert passed.content == "inner"


def test_plan_mode_prompt_injected_only_when_available():
    on = build_system_prompt(
        documents=[], memory=[], skills=[], todo_available=True
    )
    off = build_system_prompt(documents=[], memory=[], skills=[], todo_available=False)
    assert "Plan mode" in on and "todo" in on
    assert "Plan mode" not in off


# ---- E2E wiring:走真实 servicer→_build_executor 链,防「挂链漏接静默不暴露」(memory 教训)----


async def test_run_turn_exposes_todo_tool_by_default():
    import grpc
    from agent_cloud.v1 import worker_pb2, worker_pb2_grpc
    from tests.test_worker_server import _CapturingProvider, _final, create_worker_server

    provider = _CapturingProvider(_final("ok"))
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider, port=0
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            await stub.RunTurn(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    user_message="hi",
                )
            )
    finally:
        await worker_server.stop(None)
    tool_names = {t.name for t in provider.last_request.tools}
    assert "todo" in tool_names  # 默认(enabled_tools 空)暴露
    assert "Plan mode" in provider.last_request.system  # 计划模式指引同步注入


async def test_run_turn_hides_todo_when_not_enabled():
    import grpc
    from agent_cloud.v1 import worker_pb2, worker_pb2_grpc
    from tests.test_worker_server import _CapturingProvider, _final, create_worker_server

    provider = _CapturingProvider(_final("ok"))
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider, port=0
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            await stub.RunTurn(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(
                        model="m", provider="fake", enabled_tools=["bash"]
                    ),
                    user_message="hi",
                )
            )
    finally:
        await worker_server.stop(None)
    tool_names = {t.name for t in provider.last_request.tools}
    assert "todo" not in tool_names  # 显式清单不含 → 不暴露
    assert "Plan mode" not in provider.last_request.system  # 指引也不注入
