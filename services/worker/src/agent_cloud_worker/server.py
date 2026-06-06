from __future__ import annotations

from collections.abc import Callable

import grpc
from agent_cloud.v1 import worker_pb2, worker_pb2_grpc
from agent_cloud_common import ContextDocument, MemoryItem, SkillRef
from agent_cloud_common.codec import msg_from_proto, msg_to_proto

from agent_cloud_worker.context import build_system_prompt
from agent_cloud_worker.loop import run_turn
from agent_cloud_worker.provider import Provider
from agent_cloud_worker.sandbox_executor import SandboxToolExecutor

# 由 agent 的 (model, provider, key_ref) 造一个 Provider。真实实现(Anthropic 等)在后续 Plan。
ProviderFactory = Callable[[str, str, str], Provider]


class WorkerServicer(worker_pb2_grpc.WorkerServicer):
    def __init__(self, provider_factory: ProviderFactory) -> None:
        self._provider_factory = provider_factory

    async def RunTurn(
        self, request: worker_pb2.RunTurnRequest, context: grpc.aio.ServicerContext
    ) -> worker_pb2.RunTurnResponse:
        system = build_system_prompt(
            documents=[ContextDocument(d.scope, d.type, d.content) for d in request.documents],
            memory=[MemoryItem(m.scope, m.content) for m in request.memory],
            skills=[SkillRef(s.name, s.description, s.location) for s in request.skills],
        )
        history = [msg_from_proto(m) for m in request.messages]
        provider = self._provider_factory(
            request.agent.model, request.agent.provider, request.agent.key_ref
        )
        async with grpc.aio.insecure_channel(request.sandbox_endpoint) as channel:
            executor = SandboxToolExecutor(channel, request.work_subdir)
            result = await run_turn(
                provider,
                executor,
                system=system,
                history=history,
                user_message=request.user_message,
            )
        return worker_pb2.RunTurnResponse(
            new_messages=[msg_to_proto(m) for m in result.new_messages],
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            stop_reason=result.stop_reason,
        )


async def create_server(
    provider_factory: ProviderFactory, host: str = "localhost", port: int = 0
) -> tuple[grpc.aio.Server, int]:
    server = grpc.aio.server()
    worker_pb2_grpc.add_WorkerServicer_to_server(WorkerServicer(provider_factory), server)
    bound_port = server.add_insecure_port(f"{host}:{port}")
    await server.start()
    return server, bound_port
