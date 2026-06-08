from __future__ import annotations

from collections.abc import AsyncIterator

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


async def stream_turn_via_worker(
    worker_endpoint: str, request: worker_pb2.RunTurnRequest
) -> AsyncIterator[worker_pb2.TurnEvent]:
    """消费 worker 的 RunTurnStream;channel 在迭代期间保持打开。"""
    options = [
        ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
        ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
    ]
    async with grpc.aio.insecure_channel(worker_endpoint, options=options) as channel:
        stub = worker_pb2_grpc.WorkerStub(channel)
        async for event in stub.RunTurnStream(request):
            yield event


async def summarize_via_worker(
    worker_endpoint: str, request: worker_pb2.SummarizeRequest
) -> str:
    """向 worker 发起一次 Summarize(把历史折叠成摘要),返回新摘要文本。"""
    options = [
        ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
        ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
    ]
    async with grpc.aio.insecure_channel(worker_endpoint, options=options) as channel:
        resp = await worker_pb2_grpc.WorkerStub(channel).Summarize(request)
        return resp.summary
