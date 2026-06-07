import grpc
import pytest
from agent_cloud.v1 import worker_pb2, worker_pb2_grpc
from agent_cloud_worker.server import create_server


class _BoomProvider:
    async def complete(self, request):
        raise RuntimeError("upstream 500 after retries")


async def test_unary_run_turn_maps_provider_failure_to_internal():
    server, port = await create_server(provider_factory=lambda *a: _BoomProvider(), port=0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{port}") as ch:
            stub = worker_pb2_grpc.WorkerStub(ch)
            req = worker_pb2.RunTurnRequest(
                session_id="s", user_id="u",
                agent=worker_pb2.Agent(model="m", provider="openai", key_ref="r"),
                user_message="hi", sandbox_endpoint="localhost:1", work_subdir="sessions/s",
            )
            with pytest.raises(grpc.aio.AioRpcError) as ei:
                await stub.RunTurn(req)
    finally:
        await server.stop(None)
    assert ei.value.code() == grpc.StatusCode.INTERNAL
