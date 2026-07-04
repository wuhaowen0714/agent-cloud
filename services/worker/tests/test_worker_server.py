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
from agent_cloud_worker.provider import (
    ContextWindowExceeded,
    FakeProvider,
    ProviderCompleted,
    ProviderTextDelta,
)
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

    async def stream(self, request):
        self.last_request = request
        yield ProviderCompleted(message=self._result.message, usage=self._result.usage)


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


async def test_summarize_disables_thinking_and_caps_output():
    # P2:摘要要关思考(思考模型为摘要烧大段 reasoning,慢且贵)+ 限输出(摘要与旧摘要
    # 反复合并,无上限会单调增长、最终挤占上下文窗口)。
    provider = _CapturingProvider(
        CompletionResult(
            message=Message(role=Role.ASSISTANT, text="s"),
            usage=Usage(input_tokens=1, output_tokens=1),
        )
    )
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            await stub.Summarize(
                worker_pb2.SummarizeRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    prior_summary="",
                    messages=[worker_pb2.Msg(role="user", text="hi")],
                )
            )
    finally:
        await worker_server.stop(None)
    assert provider.last_request.disable_thinking is True
    assert provider.last_request.max_tokens == 3072  # 预算随「保留路径/报错原文」的 ASCII 密度上调


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


# ---- GenerateTitle:基于首条提问起短名 ----


async def test_generate_title_cleans_output():
    # 标题响应走 FakeProvider 的 title 专用槽(GenerateTitle 用 system==TITLE_SYSTEM 识别),
    # 不放回合 scripted 队列——与「标题首问即生成、和回合并发」的新行为一致。
    provider = FakeProvider([], title=_final("「快排实现」\n"))
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            resp = await stub.GenerateTitle(
                worker_pb2.GenerateTitleRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    user_message="帮我写一个快速排序",
                )
            )
    finally:
        await worker_server.stop(None)
    assert resp.title == "快排实现"
    assert resp.input_tokens == 3 and resp.output_tokens == 4


async def test_generate_title_empty_message_invalid_argument():
    provider = FakeProvider([])
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            with pytest.raises(grpc.aio.AioRpcError) as ei:
                await stub.GenerateTitle(
                    worker_pb2.GenerateTitleRequest(
                        agent=worker_pb2.Agent(model="m", provider="fake"),
                        user_message="   ",
                    )
                )
    finally:
        await worker_server.stop(None)
    assert ei.value.code() == grpc.StatusCode.INVALID_ARGUMENT


async def test_generate_title_provider_factory_failure_failed_precondition():
    def boom(*a):
        raise RuntimeError("no key")

    worker_server, wport = await create_worker_server(provider_factory=boom, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            with pytest.raises(grpc.aio.AioRpcError) as ei:
                await stub.GenerateTitle(
                    worker_pb2.GenerateTitleRequest(
                        agent=worker_pb2.Agent(model="m", provider="fake"),
                        user_message="起个名",
                    )
                )
    finally:
        await worker_server.stop(None)
    assert ei.value.code() == grpc.StatusCode.FAILED_PRECONDITION


async def test_generate_title_caps_max_tokens():
    # 起标题是几个字的产出:请求级 max_tokens=64 收紧,不给话痨模型烧输出(审查 M3)
    provider = _CapturingProvider(_final("短名"))
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            await stub.GenerateTitle(
                worker_pb2.GenerateTitleRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    user_message="问题",
                )
            )
    finally:
        await worker_server.stop(None)
    assert provider.last_request.max_tokens == 64


async def test_extract_memory_over_grpc_returns_both_blocks():
    # 双块对账走完整 gRPC 链路:四字段正确回填(spec 2026-06-11-memory-layers)
    import json as _json

    payload = _json.dumps(
        {
            "user_changed": True,
            "user_memory": "- 中文回复",
            "agent_changed": True,
            "agent_memory": "- 名字:nana",
        }
    )
    provider = FakeProvider([_final(payload)])
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            resp = await stub.ExtractMemory(
                worker_pb2.ExtractMemoryRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    user_memory="- 用户叫我nana",
                    agent_memory="",
                    messages=[worker_pb2.Msg(role="user", text="记住你叫nana")],
                    soft_max_chars=2000,
                )
            )
    finally:
        await worker_server.stop(None)
    assert resp.user_changed is True and resp.user_memory == "- 中文回复"
    assert resp.agent_changed is True and resp.agent_memory == "- 名字:nana"
    assert resp.input_tokens == 3 and resp.output_tokens == 4


async def test_extract_memory_unparseable_maps_to_internal():
    # 解析失败 → INTERNAL(后端据此不推进水位线,下次重试)
    provider = FakeProvider([_final("not json at all")])
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            with pytest.raises(grpc.aio.AioRpcError) as exc:
                await stub.ExtractMemory(
                    worker_pb2.ExtractMemoryRequest(
                        agent=worker_pb2.Agent(model="m", provider="fake"),
                        user_memory="",
                        agent_memory="",
                        messages=[worker_pb2.Msg(role="user", text="hi")],
                        soft_max_chars=2000,
                    )
                )
    finally:
        await worker_server.stop(None)
    assert exc.value.code() == grpc.StatusCode.INTERNAL


async def test_run_turn_injects_network_region_into_system():
    # network_region 经 create_server → servicer → build_system_prompt 串入 system prompt,
    # 让模型知道所在网络、避开被墙站点(否则反复 curl google/wikipedia 失败,白费回合)。
    provider = _CapturingProvider(_final("ok"))
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider, port=0, network_region="cn"
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            await stub.RunTurn(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    messages=[],
                    user_message="搜一下今天的新闻",
                    sandbox_endpoint="localhost:1",
                    work_subdir="s1",
                )
            )
    finally:
        await worker_server.stop(None)
    assert "mainland China" in provider.last_request.system
    assert "cn.bing.com" in provider.last_request.system


async def test_run_turn_stream_injects_network_region_into_system():
    # 生产实际走流式 RPC:确认 network_region 同样串入 RunTurnStream 的 system prompt。
    provider = _CapturingProvider(_final("ok"))
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider, port=0, network_region="cn"
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            async for _ in stub.RunTurnStream(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    messages=[],
                    user_message="搜一下今天的新闻",
                    sandbox_endpoint="localhost:1",
                    work_subdir="s1",
                )
            ):
                pass
    finally:
        await worker_server.stop(None)
    assert "mainland China" in provider.last_request.system
    assert "cn.bing.com" in provider.last_request.system


async def test_run_turn_exposes_web_search_tool_when_key_configured():
    # 配了平台搜索 key → web_search 出现在传给模型的 tools 里(串联:create_server → servicer
    # → _build_executor → executor.specs)。模型直接收尾不调搜索,故无需真网络。
    provider = _CapturingProvider(_final("ok"))
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider, port=0, web_search_api_key="sk-search"
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            await stub.RunTurn(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    messages=[],
                    user_message="今天世界杯谁赢了",
                    sandbox_endpoint="localhost:1",
                    work_subdir="s1",
                )
            )
    finally:
        await worker_server.stop(None)
    tool_names = {t.name for t in provider.last_request.tools}
    assert "web_search" in tool_names


async def test_run_turn_exposes_generate_image_tool_when_key_configured():
    # 配了平台图片 key → generate_image 出现在传给模型的 tools 里(串联:create_server → servicer
    # → _build_executor → executor.specs)。回归 C1:create_server 必须把 image_gen 参数传给
    # servicer(曾只改签名漏传调用,导致配了 key 仍静默不暴露)。模型直接收尾,无需真网络/沙箱。
    provider = _CapturingProvider(_final("ok"))
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider, port=0, image_gen_api_key="sk-img"
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            await stub.RunTurn(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    messages=[],
                    user_message="画一只猫",
                    sandbox_endpoint="localhost:1",
                    work_subdir="s1",
                )
            )
    finally:
        await worker_server.stop(None)
    tool_names = {t.name for t in provider.last_request.tools}
    assert "generate_image" in tool_names
    assert "edit_image" in tool_names  # edit_image 与 generate_image 同 key,一起暴露


async def test_run_turn_hides_generate_image_tool_when_no_key():
    # 没配图片 key → 不暴露 generate_image(未配图片后端优雅降级)。
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
                    messages=[],
                    user_message="画一只猫",
                    sandbox_endpoint="localhost:1",
                    work_subdir="s1",
                )
            )
    finally:
        await worker_server.stop(None)
    tool_names = {t.name for t in provider.last_request.tools}
    assert "generate_image" not in tool_names
    assert "edit_image" not in tool_names


async def test_run_turn_hides_web_search_tool_when_no_key():
    # 没配搜索 key → 不暴露 web_search(海外/未接搜索后端优雅降级);其余 worker 原生工具仍在。
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
                    messages=[],
                    user_message="hi",
                    sandbox_endpoint="localhost:1",
                    work_subdir="s1",
                )
            )
    finally:
        await worker_server.stop(None)
    tool_names = {t.name for t in provider.last_request.tools}
    assert "web_search" not in tool_names
    assert "remember" in tool_names  # 其余 worker 原生工具不受影响


async def test_max_iterations_is_configurable_and_enforced(sandbox):
    # 配 max_iterations=2,provider 两轮都只发工具调用(永不收尾)→ 第 2 轮后达上限停。
    # 若配置没透传到 loop(仍用默认 10),这两条脚本会被耗尽后报错而非干净地 max_iterations 收尾。
    sandbox_addr, _ = sandbox
    provider = FakeProvider(
        [
            _call("write_file", {"path": "a.txt", "content": "x"}),
            _call("write_file", {"path": "b.txt", "content": "y"}),
        ]
    )
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider,
        host="localhost",
        port=0,
        max_iterations=2,
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            resp = await stub.RunTurn(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    user_message="go",
                    sandbox_endpoint=sandbox_addr,
                    work_subdir="s1",
                )
            )
    finally:
        await worker_server.stop(None)
    assert resp.stop_reason == "max_iterations"


async def test_run_turn_injects_current_date_into_system():
    # worker 现算的"今天日期"经串联进 system prompt(让模型知道今天/今年,查时事不瞎猜)。
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
                    messages=[],
                    user_message="今年发生了什么",
                    sandbox_endpoint="localhost:1",
                    work_subdir="s1",
                )
            )
    finally:
        await worker_server.stop(None)
    assert "Today's date is" in provider.last_request.system


def test_timezone_offset_actually_changes_injected_date():
    # offset 真生效:相差 26h(>24h)的两时区,任意时刻注入的日期必不同(否则配置形同虚设)。
    import re

    from agent_cloud_worker.server import _build_context_and_history

    req = worker_pb2.RunTurnRequest(
        agent=worker_pb2.Agent(model="m", provider="fake"), user_message="x"
    )
    sys_plus14, _ = _build_context_and_history(req, tz_offset_hours=14)
    sys_minus12, _ = _build_context_and_history(req, tz_offset_hours=-12)
    d1 = re.search(r"Today's date is (\d{4}-\d{2}-\d{2})", sys_plus14).group(1)
    d2 = re.search(r"Today's date is (\d{4}-\d{2}-\d{2})", sys_minus12).group(1)
    assert d1 != d2


async def test_run_turn_exposes_client_actions_only_for_mobile():
    # client=mobile → set_alarm/add_calendar_event 出现在传给模型的 tools 里(串联:create_server
    # → servicer → _build_executor → ClientActionsExecutor(client=request.client).specs)。回归
    # wiring:server 必须把 request.client 传给 ClientActionsExecutor,否则 mobile 也静默不暴露
    # (同 web_search/image_gen 的漏传隐患)。模型直接收尾,无需真网络/沙箱。
    provider = _CapturingProvider(_final("ok"))
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            await stub.RunTurn(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    messages=[],
                    user_message="设个明早7点闹钟",
                    sandbox_endpoint="localhost:1",
                    work_subdir="s1",
                    client="mobile",
                )
            )
    finally:
        await worker_server.stop(None)
    tool_names = {t.name for t in provider.last_request.tools}
    assert "set_alarm" in tool_names and "add_calendar_event" in tool_names


async def test_run_turn_hides_client_actions_on_web():
    # client=web(或不设)→ 不暴露 set_alarm/add_calendar_event(web 没有系统闹钟/日历执行通道,
    # 暴露只会诱导模型调一个落不了地的工具)。其余 worker 原生工具不受影响。
    provider = _CapturingProvider(_final("ok"))
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            await stub.RunTurn(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    messages=[],
                    user_message="设个明早7点闹钟",
                    sandbox_endpoint="localhost:1",
                    work_subdir="s1",
                    client="web",
                )
            )
    finally:
        await worker_server.stop(None)
    tool_names = {t.name for t in provider.last_request.tools}
    assert "set_alarm" not in tool_names and "add_calendar_event" not in tool_names
    assert "remember" in tool_names  # 其余 worker 原生工具不受影响


# ---- E2E wiring:批准码从 RunTurnRequest.user_message 一路进拦截层(防挂链漏接)----


async def test_run_turn_blocks_dangerous_bash_e2e(sandbox):
    sandbox_addr, _ = sandbox
    provider = FakeProvider([_call("bash", {"command": "rm -rf junk"}), _final("好的")])
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            resp = await stub.RunTurn(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    user_message="清理一下",
                    sandbox_endpoint=sandbox_addr,
                    work_subdir="s1",
                )
            )
    finally:
        await worker_server.stop(None)
    tool_msgs = [m for m in resp.new_messages if m.role == "tool"]
    assert tool_msgs, "应有工具结果"
    result = tool_msgs[0].tool_results[0]
    assert result.is_error and "批准码" in result.content  # 被拦,未真执行


async def test_run_turn_approval_in_user_message_unblocks_e2e(sandbox):
    sandbox_addr, _ = sandbox
    cmd = "rm -rf junk_ok"
    from agent_cloud_common import ToolCall as _TC
    from agent_cloud_worker.danger import fingerprint as _fp

    fp = _fp(_TC(id="x", name="bash", arguments={"command": cmd}))
    provider = FakeProvider([_call("bash", {"command": cmd}), _final("已删除")])
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            resp = await stub.RunTurn(
                worker_pb2.RunTurnRequest(
                    agent=worker_pb2.Agent(model="m", provider="fake"),
                    user_message=f"允许执行该操作(批准码 {fp})",
                    sandbox_endpoint=sandbox_addr,
                    work_subdir="s1",
                )
            )
    finally:
        await worker_server.stop(None)
    tool_msgs = [m for m in resp.new_messages if m.role == "tool"]
    result = tool_msgs[0].tool_results[0]
    assert "批准码" not in result.content  # 放行:真跑了命令(rm 一个不存在目录,成功)
    assert not result.is_error
