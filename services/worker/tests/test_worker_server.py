import grpc
import pytest
import pytest_asyncio
from agent_cloud.v1 import worker_pb2, worker_pb2_grpc
from agent_cloud_common import (
    MAX_GRPC_MESSAGE_BYTES,
    CompletionResult,
    Message,
    Role,
    ToolCall,
    TurnDone,
    Usage,
)
from agent_cloud_common.codec import turn_event_from_proto
from agent_cloud_sandbox.server import create_server as create_sandbox_server
from agent_cloud_worker.provider import ContextWindowExceeded, FakeProvider, ProviderTextDelta
from agent_cloud_worker.server import create_server as create_worker_server

_GRPC_OPTIONS = [
    ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
    ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
]


@pytest_asyncio.fixture
async def sandbox(tmp_path):
    server, port = await create_sandbox_server(base_workdir=tmp_path, host="localhost", port=0)
    yield f"localhost:{port}", tmp_path
    await server.stop(None)


def _call(tool, args):
    return CompletionResult(
        message=Message(
            role=Role.ASSISTANT, tool_calls=[ToolCall(id="c1", name=tool, arguments=args)]
        ),
        usage=Usage(input_tokens=3, output_tokens=4),
    )


def _final(text):
    return CompletionResult(
        message=Message(role=Role.ASSISTANT, text=text),
        usage=Usage(input_tokens=3, output_tokens=4),
    )


def _multi_call(calls):
    return CompletionResult(
        message=Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(id=cid, name=name, arguments=args) for cid, name, args in calls],
        ),
        usage=Usage(input_tokens=3, output_tokens=4),
    )


async def test_run_turn_over_grpc_executes_tool(sandbox):
    sandbox_addr, base = sandbox
    provider = FakeProvider(
        [
            _call("write_file", {"path": "hello.txt", "content": "from-agent"}),
            _final("done"),
        ]
    )
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider,
        host="localhost",
        port=0,
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            resp = await stub.RunTurn(
                worker_pb2.RunTurnRequest(
                    session_id="s1",
                    user_id="u1",
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    documents=[worker_pb2.Doc(scope="user", type="USER", content="# u")],
                    messages=[],
                    user_message="write the file",
                    sandbox_endpoint=sandbox_addr,
                    work_subdir="s1",
                )
            )
    finally:
        await worker_server.stop(None)

    assert resp.stop_reason == "end_turn"
    assert [m.role for m in resp.new_messages] == ["assistant", "tool", "assistant"]
    assert resp.output_tokens == 8  # 两次 provider 调用累加
    assert (base / "s1" / "hello.txt").read_text() == "from-agent"


async def test_run_turn_history_passed_through(sandbox):
    sandbox_addr, _ = sandbox
    provider = FakeProvider([_final("ok")])
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider,
        host="localhost",
        port=0,
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            resp = await stub.RunTurn(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    messages=[
                        worker_pb2.Msg(role="user", text="earlier"),
                        worker_pb2.Msg(role="assistant", text="reply"),
                    ],
                    user_message="now",
                    sandbox_endpoint=sandbox_addr,
                    work_subdir="s1",
                )
            )
    finally:
        await worker_server.stop(None)
    assert resp.stop_reason == "end_turn"
    assert len(resp.new_messages) == 1 and resp.new_messages[0].text == "ok"


# ---- I1: 畸形请求 → 明确的 gRPC code,而不是 UNKNOWN ----


async def test_run_turn_invalid_role_returns_invalid_argument(sandbox):
    sandbox_addr, _ = sandbox
    provider = FakeProvider([_final("ok")])
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider, host="localhost", port=0
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            with pytest.raises(grpc.aio.AioRpcError) as ei:
                await stub.RunTurn(
                    worker_pb2.RunTurnRequest(
                        agent=worker_pb2.Agent(model="m", provider="fake"),
                        messages=[worker_pb2.Msg(role="system", text="bad role")],
                        user_message="now",
                        sandbox_endpoint=sandbox_addr,
                        work_subdir="s1",
                    )
                )
    finally:
        await worker_server.stop(None)
    assert ei.value.code() == grpc.StatusCode.INVALID_ARGUMENT


async def test_run_turn_malformed_arguments_json_returns_invalid_argument(sandbox):
    sandbox_addr, _ = sandbox
    provider = FakeProvider([_final("ok")])
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider, host="localhost", port=0
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            with pytest.raises(grpc.aio.AioRpcError) as ei:
                await stub.RunTurn(
                    worker_pb2.RunTurnRequest(
                        agent=worker_pb2.Agent(model="m", provider="fake"),
                        messages=[
                            worker_pb2.Msg(
                                role="assistant",
                                tool_calls=[
                                    worker_pb2.ToolCall(id="c1", name="bash", arguments_json="{bad")
                                ],
                            )
                        ],
                        user_message="now",
                        sandbox_endpoint=sandbox_addr,
                        work_subdir="s1",
                    )
                )
    finally:
        await worker_server.stop(None)
    assert ei.value.code() == grpc.StatusCode.INVALID_ARGUMENT


async def test_run_turn_provider_factory_failure_returns_failed_precondition(sandbox):
    sandbox_addr, _ = sandbox

    def boom(*_a):
        raise RuntimeError("unknown provider: nope")

    worker_server, wport = await create_worker_server(
        provider_factory=boom, host="localhost", port=0
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            with pytest.raises(grpc.aio.AioRpcError) as ei:
                await stub.RunTurn(
                    worker_pb2.RunTurnRequest(
                        agent=worker_pb2.Agent(model="m", provider="nope"),
                        messages=[],
                        user_message="now",
                        sandbox_endpoint=sandbox_addr,
                        work_subdir="s1",
                    )
                )
    finally:
        await worker_server.stop(None)
    assert ei.value.code() == grpc.StatusCode.FAILED_PRECONDITION


# ---- I2: 超过 gRPC 默认 4MB 的回合在共享上限下仍能成功返回 ----


async def test_run_turn_large_response_under_shared_limit(sandbox):
    sandbox_addr, _ = sandbox
    big = "x" * 5_000_000  # > 4MB 默认接收上限
    provider = FakeProvider([_final(big)])
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider, host="localhost", port=0
    )
    try:
        async with grpc.aio.insecure_channel(
            f"localhost:{wport}", options=_GRPC_OPTIONS
        ) as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            resp = await stub.RunTurn(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    messages=[],
                    user_message="now",
                    sandbox_endpoint=sandbox_addr,
                    work_subdir="s1",
                )
            )
    finally:
        await worker_server.stop(None)
    assert resp.stop_reason == "end_turn"
    assert len(resp.new_messages[-1].text) >= 5_000_000


# ---- Coverage backfill ----


async def test_run_turn_unreachable_sandbox_yields_tool_error():
    # sandbox_endpoint 指向一个无人监听的端口:工具执行经 SandboxToolExecutor 捕获 RPC
    # 失败,转成 is_error=True 的 tool 结果,回合仍能正常收尾。
    provider = FakeProvider(
        [
            _call("write_file", {"path": "x.txt", "content": "y"}),
            _final("done"),
        ]
    )
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider, host="localhost", port=0
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            resp = await stub.RunTurn(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    messages=[],
                    user_message="write the file",
                    sandbox_endpoint="localhost:1",
                    work_subdir="s1",
                )
            )
    finally:
        await worker_server.stop(None)
    assert resp.stop_reason == "end_turn"
    tool_msgs = [m for m in resp.new_messages if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert len(tool_msgs[0].tool_results) == 1
    assert tool_msgs[0].tool_results[0].is_error is True


async def test_run_turn_multiple_tool_calls_single_round(sandbox):
    sandbox_addr, base = sandbox
    provider = FakeProvider(
        [
            _multi_call(
                [
                    ("c1", "write_file", {"path": "a.txt", "content": "AA"}),
                    ("c2", "write_file", {"path": "b.txt", "content": "BB"}),
                ]
            ),
            _final("done"),
        ]
    )
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider, host="localhost", port=0
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            resp = await stub.RunTurn(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    messages=[],
                    user_message="write both",
                    sandbox_endpoint=sandbox_addr,
                    work_subdir="s1",
                )
            )
    finally:
        await worker_server.stop(None)
    assert resp.stop_reason == "end_turn"
    assert [m.role for m in resp.new_messages] == ["assistant", "tool", "assistant"]
    tool_msg = resp.new_messages[1]
    assert len(tool_msg.tool_results) == 2
    assert {r.call_id for r in tool_msg.tool_results} == {"c1", "c2"}
    assert (base / "s1" / "a.txt").read_text() == "AA"
    assert (base / "s1" / "b.txt").read_text() == "BB"


# ---- Plan 3b: 流式 RunTurnStream over gRPC ----


async def test_run_turn_stream_over_grpc(sandbox):
    sandbox_addr, base = sandbox
    provider = FakeProvider(
        [
            _call("write_file", {"path": "hello.txt", "content": "from-agent"}),
            _final("done"),
        ]
    )
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    events = []
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            async for proto_ev in stub.RunTurnStream(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    messages=[],
                    user_message="write it",
                    sandbox_endpoint=sandbox_addr,
                    work_subdir="s1",
                )
            ):
                events.append(turn_event_from_proto(proto_ev))
    finally:
        await worker_server.stop(None)

    kinds = [type(e).__name__ for e in events]
    assert "ToolCallStarted" in kinds and "ToolResultEvent" in kinds
    assert isinstance(events[-1], TurnDone) and events[-1].stop_reason == "end_turn"
    assert [m.role.value for m in events[-1].new_messages] == ["assistant", "tool", "assistant"]
    assert (base / "s1" / "hello.txt").read_text() == "from-agent"


# ---- M3: 流式大 TurnDone(>4MB 默认上限)在共享上限 + 正确配置的 client 下成功 ----


async def test_run_turn_stream_large_turn_done_under_shared_limit(sandbox):
    sandbox_addr, _ = sandbox
    big = "x" * 5_000_000  # > 4MB 默认接收上限
    provider = FakeProvider([_final(big)])
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    events = []
    try:
        async with grpc.aio.insecure_channel(
            f"localhost:{wport}", options=_GRPC_OPTIONS
        ) as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            async for proto_ev in stub.RunTurnStream(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    messages=[],
                    user_message="now",
                    sandbox_endpoint=sandbox_addr,
                    work_subdir="s1",
                )
            ):
                events.append(turn_event_from_proto(proto_ev))
    finally:
        await worker_server.stop(None)
    assert isinstance(events[-1], TurnDone) and events[-1].stop_reason == "end_turn"
    assert len(events[-1].new_messages[-1].text) >= 5_000_000


# ---- Plan 12a: Summarize RPC ----


async def test_summarize_returns_summary_and_usage():
    provider = FakeProvider([_final("摘要:用户要排序,已完成 bubble sort。")])
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            resp = await stub.Summarize(
                worker_pb2.SummarizeRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    prior_summary="",
                    messages=[
                        worker_pb2.Msg(role="user", text="帮我排序"),
                        worker_pb2.Msg(role="assistant", text="好的,用 bubble sort"),
                    ],
                )
            )
    finally:
        await worker_server.stop(None)
    assert "摘要" in resp.summary
    assert resp.input_tokens == 3 and resp.output_tokens == 4


class _CapturingProvider:
    def __init__(self, result):
        self._result = result
        self.last_request = None

    async def complete(self, request):
        self.last_request = request
        return self._result


async def test_summarize_puts_prior_summary_in_system_not_user_message():
    # I3:已有摘要应进入 system(系统提供的已有产物),而非塞进末尾 user 消息(会被当成新指令)。
    provider = _CapturingProvider(
        CompletionResult(
            message=Message(role=Role.ASSISTANT, text="merged"),
            usage=Usage(input_tokens=1, output_tokens=1),
        )
    )
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            resp = await stub.Summarize(
                worker_pb2.SummarizeRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    prior_summary="OLD_SUMMARY_TEXT",
                    messages=[worker_pb2.Msg(role="user", text="新消息")],
                )
            )
    finally:
        await worker_server.stop(None)
    assert resp.summary == "merged"
    assert "OLD_SUMMARY_TEXT" in provider.last_request.system
    assert provider.last_request.messages[-1].role == Role.USER
    assert "OLD_SUMMARY_TEXT" not in provider.last_request.messages[-1].text


async def test_summarize_only_prior_summary_echoes_without_llm():
    # I4:无新历史、只有已有摘要 → 原样回显,不调用 provider(空脚本被调用会 IndexError→INTERNAL)。
    provider = FakeProvider([])
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            resp = await stub.Summarize(
                worker_pb2.SummarizeRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    prior_summary="只有这段摘要",
                    messages=[],
                )
            )
    finally:
        await worker_server.stop(None)
    assert resp.summary == "只有这段摘要"
    assert resp.input_tokens == 0 and resp.output_tokens == 0


async def test_summarize_empty_request_returns_invalid_argument():
    # I4:既无历史又无已有摘要 → INVALID_ARGUMENT,不白烧一次上游调用。
    provider = FakeProvider([])
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            with pytest.raises(grpc.aio.AioRpcError) as ei:
                await stub.Summarize(
                    worker_pb2.SummarizeRequest(
                        agent=worker_pb2.Agent(model="m", provider="fake"),
                        prior_summary="",
                        messages=[],
                    )
                )
    finally:
        await worker_server.stop(None)
    assert ei.value.code() == grpc.StatusCode.INVALID_ARGUMENT


async def test_summarize_invalid_role_returns_invalid_argument():
    provider = FakeProvider([_final("x")])
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            with pytest.raises(grpc.aio.AioRpcError) as ei:
                await stub.Summarize(
                    worker_pb2.SummarizeRequest(
                        agent=worker_pb2.Agent(model="m", provider="fake"),
                        messages=[worker_pb2.Msg(role="system", text="bad role")],
                    )
                )
    finally:
        await worker_server.stop(None)
    assert ei.value.code() == grpc.StatusCode.INVALID_ARGUMENT


# ---- Plan 12a: 上下文超窗 → RESOURCE_EXHAUSTED ----


class _ContextOverflowProvider:
    async def complete(self, request):
        raise ContextWindowExceeded("context window exceeded")

    async def stream(self, request):
        raise ContextWindowExceeded("context window exceeded")
        yield  # pragma: no cover — 使其成为 async generator


async def test_run_turn_context_overflow_maps_to_resource_exhausted():
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: _ContextOverflowProvider(), port=0
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            with pytest.raises(grpc.aio.AioRpcError) as ei:
                await stub.RunTurn(
                    worker_pb2.RunTurnRequest(
                        agent=worker_pb2.Agent(model="m", provider="fake"),
                        messages=[],
                        user_message="go",
                        sandbox_endpoint="localhost:1",
                        work_subdir="s1",
                    )
                )
    finally:
        await worker_server.stop(None)
    assert ei.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED


async def test_run_turn_stream_context_overflow_maps_to_resource_exhausted():
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: _ContextOverflowProvider(), port=0
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            with pytest.raises(grpc.aio.AioRpcError) as ei:
                async for _ in stub.RunTurnStream(
                    worker_pb2.RunTurnRequest(
                        agent=worker_pb2.Agent(model="m", provider="fake"),
                        messages=[],
                        user_message="go",
                        sandbox_endpoint="localhost:1",
                        work_subdir="s1",
                    )
                ):
                    pass
    finally:
        await worker_server.stop(None)
    assert ei.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED


async def test_run_turn_stream_invalid_role_aborts(sandbox):
    sandbox_addr, _ = sandbox
    provider = FakeProvider([_final("x")])
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            with pytest.raises(grpc.aio.AioRpcError) as ei:
                async for _ in stub.RunTurnStream(
                    worker_pb2.RunTurnRequest(
                        agent=worker_pb2.Agent(model="m", provider="fake"),
                        messages=[worker_pb2.Msg(role="system", text="bad")],
                        user_message="x",
                        sandbox_endpoint=sandbox_addr,
                        work_subdir="s1",
                    )
                ):
                    pass
    finally:
        await worker_server.stop(None)
    assert ei.value.code() == grpc.StatusCode.INVALID_ARGUMENT


# ---- I1: 流中途失败 → 干净的 INTERNAL,不泄漏原始异常文本 ----


class _PartialThenNoCompletedProvider:
    """流式 provider:吐一个 TextDelta 后直接结束,**不**发 ProviderCompleted。

    这会触发 run_turn_stream 里的守卫 RuntimeError(provider stream ended without a
    ProviderCompleted event),用于验证 server 把流中途异常收敛为 INTERNAL。
    """

    async def stream(self, request):
        yield ProviderTextDelta(text="partial")


async def test_run_turn_stream_midstream_failure_returns_internal(sandbox):
    sandbox_addr, _ = sandbox
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: _PartialThenNoCompletedProvider(), port=0
    )
    events = []
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            with pytest.raises(grpc.aio.AioRpcError) as ei:
                async for proto_ev in stub.RunTurnStream(
                    worker_pb2.RunTurnRequest(
                        agent=worker_pb2.Agent(model="m", provider="fake"),
                        messages=[],
                        user_message="go",
                        sandbox_endpoint=sandbox_addr,
                        work_subdir="s1",
                    )
                ):
                    events.append(turn_event_from_proto(proto_ev))
    finally:
        await worker_server.stop(None)
    # 客户端先收到了部分 TextDelta
    assert [type(e).__name__ for e in events] == ["TextDelta"]
    assert events[0].text == "partial"
    # 然后流以 INTERNAL 结束,且不泄漏原始异常文本
    assert ei.value.code() == grpc.StatusCode.INTERNAL
    assert "ProviderCompleted" not in (ei.value.details() or "")
