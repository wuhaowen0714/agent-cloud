from __future__ import annotations

import json
import logging
from collections.abc import Callable

import grpc
from agent_cloud.v1 import worker_pb2, worker_pb2_grpc
from agent_cloud_common import (
    MAX_GRPC_MESSAGE_BYTES,
    CompletionRequest,
    ContextDocument,
    MemoryItem,
    Message,
    Role,
    SkillRef,
)
from agent_cloud_common.codec import msg_from_proto, msg_to_proto, turn_event_to_proto

from agent_cloud_worker.context import build_system_prompt
from agent_cloud_worker.loop import run_turn, run_turn_stream
from agent_cloud_worker.memory_extract import MemoryParseError, reconcile_memory
from agent_cloud_worker.provider import (
    CompletionBudgetExceeded,
    ContextWindowExceeded,
    Provider,
)
from agent_cloud_worker.remember import RememberingExecutor, remember_enabled
from agent_cloud_worker.sandbox_executor import SandboxToolExecutor
from agent_cloud_worker.title import TITLE_SYSTEM, clean_title

logger = logging.getLogger(__name__)

# 由 agent 的 (model, provider, api_key, base_url) 造一个 Provider。
ProviderFactory = Callable[[str, str, str, str], Provider]

# 压缩器系统提示词:把历史浓缩成简明要点,保留后续回合需要的信息(spec §6)。
_SUMMARIZE_SYSTEM = (
    "你是对话压缩器。把给定对话浓缩成简明要点,保留:用户的目标与诉求、关键事实与决定、"
    "已产出的文件与成果、尚未完成的事项。保留后续对话需要的上下文,去掉寒暄与冗余。"
    "只输出要点本身,不要额外解释。"
)


def _build_context_and_history(request: worker_pb2.RunTurnRequest) -> tuple[str, list]:
    system = build_system_prompt(
        documents=[ContextDocument(d.scope, d.type, d.content) for d in request.documents],
        memory=[MemoryItem(m.scope, m.content) for m in request.memory],
        skills=[SkillRef(s.name, s.description, s.location) for s in request.skills],
        history_summary=request.history_summary,
    )
    history = [msg_from_proto(m) for m in request.messages]
    return system, history


class WorkerServicer(worker_pb2_grpc.WorkerServicer):
    def __init__(self, provider_factory: ProviderFactory) -> None:
        self._provider_factory = provider_factory

    async def RunTurn(
        self, request: worker_pb2.RunTurnRequest, context: grpc.aio.ServicerContext
    ) -> worker_pb2.RunTurnResponse:
        # 解码客户端输入。畸形输入(非法 role / 坏 arguments_json)是 client-fault,
        # 必须映射成 INVALID_ARGUMENT,而不是冒泡成无法与真实 worker bug 区分的 UNKNOWN。
        try:
            system, history = _build_context_and_history(request)
        except (ValueError, json.JSONDecodeError) as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            return

        # provider_factory 失败(如未知 provider)也是 client/config-fault,而非 worker bug。
        try:
            provider = self._provider_factory(
                request.agent.model,
                request.agent.provider,
                request.agent.api_key,
                request.agent.base_url,
            )
        except Exception as exc:  # noqa: BLE001 — 故意把工厂的任意失败收敛为明确状态码
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, f"provider unavailable: {exc}")
            return

        async with grpc.aio.insecure_channel(
            request.sandbox_endpoint,
            options=[
                ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
                ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
            ],
        ) as channel:
            executor = RememberingExecutor(
                SandboxToolExecutor(
                    channel,
                    request.work_subdir,
                    list(request.agent.enabled_tools),
                    token=request.sandbox_token,
                ),
                enabled=remember_enabled(list(request.agent.enabled_tools)),
            )
            try:
                result = await run_turn(
                    provider,
                    executor,
                    system=system,
                    history=history,
                    user_message=request.user_message,
                )
            except CompletionBudgetExceeded as exc:
                # 配置错误(输出预算 ≥ 模型窗口):压缩救不了,绝不能映射成 RESOURCE_EXHAUSTED
                # 触发后端无效压缩螺旋;FAILED_PRECONDITION = 调低 REQUEST_MAX_TOKENS。
                logger.warning("completion budget exceeds model window: %s", exc)
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "configured request_max_tokens exceeds the model context window; "
                    "lower AGENT_CLOUD_WORKER_REQUEST_MAX_TOKENS",
                )
                return
            except ContextWindowExceeded:
                # 上下文超窗:可恢复,映射成 RESOURCE_EXHAUSTED(区别于下面的 INTERNAL),
                # 后端据此触发压缩并提示用户重试(spec §6/§8)。
                logger.info("RunTurn context window exceeded")
                await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "context window exceeded")
                return
            except Exception:
                # provider 失败(超时/重试耗尽/上游 5xx)或 loop 守卫:收敛为 INTERNAL,
                # 不把原始异常泄漏给客户端(与 RunTurnStream 一致)。后端会转成 502,
                # 回合失败但无半成品(assistant 消息仅成功后落库)。
                logger.exception("RunTurn failed")
                await context.abort(grpc.StatusCode.INTERNAL, "turn failed")
                return
        return worker_pb2.RunTurnResponse(
            new_messages=[msg_to_proto(m) for m in result.new_messages],
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            stop_reason=result.stop_reason,
            context_tokens=result.context_tokens,
        )

    async def RunTurnStream(
        self, request: worker_pb2.RunTurnRequest, context: grpc.aio.ServicerContext
    ):
        # 解码 / 工厂失败在第一个 yield 之前 abort(client/config-fault),映射成明确状态码。
        try:
            system, history = _build_context_and_history(request)
        except (ValueError, json.JSONDecodeError) as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            return
        try:
            provider = self._provider_factory(
                request.agent.model,
                request.agent.provider,
                request.agent.api_key,
                request.agent.base_url,
            )
        except Exception as exc:  # noqa: BLE001 — 故意把工厂的任意失败收敛为明确状态码
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, f"provider unavailable: {exc}")
            return

        options = [
            ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
            ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
        ]
        async with grpc.aio.insecure_channel(request.sandbox_endpoint, options=options) as channel:
            executor = RememberingExecutor(
                SandboxToolExecutor(
                    channel,
                    request.work_subdir,
                    list(request.agent.enabled_tools),
                    token=request.sandbox_token,
                ),
                enabled=remember_enabled(list(request.agent.enabled_tools)),
            )
            # 流中途失败(provider 抛错 / loop 守卫)是 worker-fault:收敛为通用 INTERNAL,
            # 不把原始异常文本泄漏给客户端(会暴露内部细节且与 UNKNOWN 无法区分)。
            # context.abort 不在 run_turn_stream 内调用,故此处的宽 except 是安全的。
            try:
                async for event in run_turn_stream(
                    provider,
                    executor,
                    system=system,
                    history=history,
                    user_message=request.user_message,
                ):
                    yield turn_event_to_proto(event)
            except CompletionBudgetExceeded as exc:
                # 配置错误(输出预算 ≥ 模型窗口):压缩救不了,绝不能映射成 RESOURCE_EXHAUSTED
                # 触发后端无效压缩螺旋;FAILED_PRECONDITION = 调低 REQUEST_MAX_TOKENS。
                logger.warning("completion budget exceeds model window: %s", exc)
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "configured request_max_tokens exceeds the model context window; "
                    "lower AGENT_CLOUD_WORKER_REQUEST_MAX_TOKENS",
                )
                return
            except ContextWindowExceeded:
                # 上下文超窗:可恢复 → RESOURCE_EXHAUSTED,后端据此触发压缩并提示重试。
                # 注意:多轮工具循环下,超窗可能发生在本 RPC **已 yield 过前几轮增量之后**
                # (第 2+ 次 provider.stream 才超)。客户端收到 RESOURCE_EXHAUSTED 时必须丢弃
                # 本回合所有已收增量,整回合作废(assistant 消息仅成功收尾后才落库,故无半成品)。
                logger.info("RunTurnStream context window exceeded")
                await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "context window exceeded")
                return
            except Exception:
                logger.exception("RunTurnStream failed mid-stream")
                await context.abort(grpc.StatusCode.INTERNAL, "turn failed")
                return

    async def Summarize(
        self, request: worker_pb2.SummarizeRequest, context: grpc.aio.ServicerContext
    ) -> worker_pb2.SummarizeResponse:
        # 把历史(+已有摘要)折叠成一份更新后的摘要。一次 LLM 调用,不用工具。
        try:
            history = [msg_from_proto(m) for m in request.messages]
        except (ValueError, json.JSONDecodeError) as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            return

        # 空请求短路,不白烧一次上游调用:
        if not history and not request.prior_summary:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "nothing to summarize")
            return
        if not history:
            # 只有已有摘要、没有新历史可合并:原样回显,省一次 LLM 调用。
            return worker_pb2.SummarizeResponse(
                summary=request.prior_summary, input_tokens=0, output_tokens=0
            )

        try:
            provider = self._provider_factory(
                request.agent.model,
                request.agent.provider,
                request.agent.api_key,
                request.agent.base_url,
            )
        except Exception as exc:  # noqa: BLE001 — 工厂任意失败收敛为明确状态码
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, f"provider unavailable: {exc}")
            return

        # 已有摘要放进 system(它是"系统提供的已有产物"),而非塞进末尾 user 消息 ——
        # 否则模型容易把它误读成"用户在对话末尾贴的新指令",与历史里的真实 user 指令混淆。
        system = _SUMMARIZE_SYSTEM
        if request.prior_summary:
            system = f"{_SUMMARIZE_SYSTEM}\n\n# 已有摘要(需与下面对话合并)\n{request.prior_summary}"
            instruction = "请把【已有摘要】与以上对话合并,输出一份完整、自洽的要点摘要。"
        else:
            instruction = "请将以上对话压缩成简明要点。"
        messages = [*history, Message(role=Role.USER, text=instruction)]

        try:
            result = await provider.complete(
                CompletionRequest(system=system, messages=messages, tools=[])
            )
        except CompletionBudgetExceeded as exc:
            # 配置错误(输出预算 ≥ 模型窗口):压缩救不了,绝不能映射成 RESOURCE_EXHAUSTED
            # 触发后端无效压缩螺旋;FAILED_PRECONDITION = 调低 REQUEST_MAX_TOKENS。
            logger.warning("completion budget exceeds model window: %s", exc)
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "configured request_max_tokens exceeds the model context window; "
                "lower AGENT_CLOUD_WORKER_REQUEST_MAX_TOKENS",
            )
            return
        except ContextWindowExceeded:
            # 连摘要请求都超窗:可恢复,交给后端用更激进的折叠边界重试(spec §6/§8)。
            logger.info("Summarize context window exceeded")
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "context window exceeded")
            return
        except Exception:
            logger.exception("Summarize failed")
            await context.abort(grpc.StatusCode.INTERNAL, "summarize failed")
            return
        return worker_pb2.SummarizeResponse(
            summary=result.message.text,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )

    async def GenerateTitle(
        self, request: worker_pb2.GenerateTitleRequest, context: grpc.aio.ServicerContext
    ) -> worker_pb2.GenerateTitleResponse:
        # 基于首条用户提问起 ≤16 字短名。一次小 LLM 调用,不用工具;清洗在 worker 侧。
        text = request.user_message.strip()
        if not text:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "empty user_message")
            return
        try:
            provider = self._provider_factory(
                request.agent.model,
                request.agent.provider,
                request.agent.api_key,
                request.agent.base_url,
            )
        except Exception as exc:  # noqa: BLE001 — 同 Summarize:工厂任意失败收敛为状态码
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, f"provider unavailable: {exc}")
            return
        try:
            result = await provider.complete(
                CompletionRequest(
                    system=TITLE_SYSTEM,
                    # 起名不需要全文:截前 2000 字符,长提问不白烧 token
                    messages=[Message(role=Role.USER, text=text[:2000])],
                    tools=[],
                    max_tokens=64,  # 几个字的产出,不给话痨模型烧输出的空间
                )
            )
        except Exception:
            logger.exception("GenerateTitle failed")
            await context.abort(grpc.StatusCode.INTERNAL, "title generation failed")
            return
        return worker_pb2.GenerateTitleResponse(
            title=clean_title(result.message.text),
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )

    async def ExtractMemory(
        self, request: worker_pb2.ExtractMemoryRequest, context: grpc.aio.ServicerContext
    ) -> worker_pb2.ExtractMemoryResponse:
        # 记忆提炼(双块:user + agent,错层归位)。一次 LLM 调用,不用工具。
        try:
            messages = [msg_from_proto(m) for m in request.messages]
        except (ValueError, json.JSONDecodeError) as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            return
        if not messages:  # 没有新消息可提炼:原样回显,省一次上游调用
            return worker_pb2.ExtractMemoryResponse(
                user_memory=request.user_memory,
                agent_memory=request.agent_memory,
                user_changed=False,
                agent_changed=False,
                input_tokens=0,
                output_tokens=0,
            )
        try:
            provider = self._provider_factory(
                request.agent.model,
                request.agent.provider,
                request.agent.api_key,
                request.agent.base_url,
            )
        except Exception as exc:  # noqa: BLE001 — 工厂任意失败收敛为明确状态码
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, f"provider unavailable: {exc}")
            return
        try:
            user_mem, user_changed, agent_mem, agent_changed, usage = await reconcile_memory(
                provider,
                user_current=request.user_memory,
                agent_current=request.agent_memory,
                messages=messages,
                soft_max_chars=request.soft_max_chars or 2000,
            )
        except CompletionBudgetExceeded as exc:
            # 配置错误(输出预算 ≥ 模型窗口):压缩救不了,绝不能映射成 RESOURCE_EXHAUSTED
            # 触发后端无效压缩螺旋;FAILED_PRECONDITION = 调低 REQUEST_MAX_TOKENS。
            logger.warning("completion budget exceeds model window: %s", exc)
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "configured request_max_tokens exceeds the model context window; "
                "lower AGENT_CLOUD_WORKER_REQUEST_MAX_TOKENS",
            )
            return
        except ContextWindowExceeded:
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "context window exceeded")
            return
        except MemoryParseError:
            # 模型输出无法解析:收敛为 INTERNAL(可重试),后端据此不推进水位线。
            logger.warning("ExtractMemory: unparseable model output")
            await context.abort(grpc.StatusCode.INTERNAL, "memory extraction failed to parse")
            return
        except Exception:
            logger.exception("ExtractMemory failed")
            await context.abort(grpc.StatusCode.INTERNAL, "extract memory failed")
            return
        return worker_pb2.ExtractMemoryResponse(
            user_memory=user_mem,
            agent_memory=agent_mem,
            user_changed=user_changed,
            agent_changed=agent_changed,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )


async def create_server(
    provider_factory: ProviderFactory, host: str = "localhost", port: int = 0
) -> tuple[grpc.aio.Server, int]:
    server = grpc.aio.server(
        options=[
            ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
            ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
        ]
    )
    worker_pb2_grpc.add_WorkerServicer_to_server(WorkerServicer(provider_factory), server)
    bound_port = server.add_insecure_port(f"{host}:{port}")
    await server.start()
    return server, bound_port
