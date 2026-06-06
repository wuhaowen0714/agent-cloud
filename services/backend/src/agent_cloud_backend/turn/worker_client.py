from __future__ import annotations

import grpc

from agent_cloud.v1 import worker_pb2, worker_pb2_grpc
from agent_cloud_common import MAX_GRPC_MESSAGE_BYTES


async def run_turn_via_worker(
    worker_endpoint: str, request: worker_pb2.RunTurnRequest
) -> worker_pb2.RunTurnResponse:
    """向 worker 发起一次 RunTurn(一元)。消息上限与 worker 端一致。"""
    options = [
        ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
        ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
    ]
    async with grpc.aio.insecure_channel(worker_endpoint, options=options) as channel:
        stub = worker_pb2_grpc.WorkerStub(channel)
        return await stub.RunTurn(request)
