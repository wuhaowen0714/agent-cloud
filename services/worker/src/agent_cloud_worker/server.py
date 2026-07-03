from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import grpc
from agent_cloud.v1 import sandbox_pb2_grpc, worker_pb2, worker_pb2_grpc
from agent_cloud_common import (
    MAX_GRPC_MESSAGE_BYTES,
    CompletionRequest,
    ContextDocument,
    MemoryItem,
    Message,
    Role,
    SkillRef,
    TurnDone,
    Usage,
)
from agent_cloud_common.codec import msg_from_proto, msg_to_proto, turn_event_to_proto

from agent_cloud_worker.client_actions import ClientActionsExecutor
from agent_cloud_worker.context import build_system_prompt
from agent_cloud_worker.image_gen import (
    DEFAULT_IMAGE_EDIT_MODEL,
    DEFAULT_IMAGE_ENDPOINT,
    DEFAULT_IMAGE_MODEL,
    ImageEditExecutor,
    ImageGenExecutor,
    downscale_for_vision,
    edit_image_enabled,
    generate_image_enabled,
    make_sophnet_image_generator,
    to_data_uri,
)
from agent_cloud_worker.loop import _Tagged, run_turn, run_turn_stream
from agent_cloud_worker.memory_extract import MemoryParseError, reconcile_memory
from agent_cloud_worker.notify import NotifyingExecutor, notify_enabled
from agent_cloud_worker.provider import (
    CompletionBudgetExceeded,
    ContextWindowExceeded,
    Provider,
)
from agent_cloud_worker.remember import RememberingExecutor, remember_enabled
from agent_cloud_worker.sandbox_executor import SandboxToolExecutor
from agent_cloud_worker.schedule_task import SchedulingExecutor, schedule_task_enabled
from agent_cloud_worker.subagent import SubagentExecutor, subagent_enabled
from agent_cloud_worker.title import TITLE_SYSTEM, clean_title
from agent_cloud_worker.web_search import (
    DEFAULT_SEARCH_ENDPOINT,
    WebSearchExecutor,
    make_sophnet_searcher,
    web_search_enabled,
)

logger = logging.getLogger(__name__)


async def _read_turn_images(read_binary, paths: list[str]) -> list[str]:
    """工作区图片路径经沙箱 ReadBinary 读成 data_uri;单张失败跳过(不中断回合)。"""
    out: list[str] = []
    for p in paths:
        try:
            data = await read_binary(p)
        except Exception:  # noqa: BLE001 — 单图读失败不该炸掉整个回合
            logger.warning("turn image read failed, skipping: %s", p)
            continue
        comp, mime = downscale_for_vision(data)  # 超大图缩放压缩,避免撞 sophnet 请求体限制
        out.append(to_data_uri(p, comp, mime))
    return out


# 由 agent 的 (model, provider, api_key, base_url) 造一个 Provider。
ProviderFactory = Callable[[str, str, str, str], Provider]

# 压缩器系统提示词:把历史浓缩成简明要点,保留后续回合需要的信息(spec §6)。
# 长度预算:摘要每次压缩都与旧摘要合并,无约束会单调增长——最终摘要本身挤占上下文窗口,
# 反过来加剧超窗(force_compact 只剩 1 条也救不了)。预算 + "优先精简更早内容"让它有损滚动。
_SUMMARIZE_SYSTEM = (
    "你是对话压缩器。把给定对话浓缩成简明要点,保留:用户的目标与诉求、关键事实与决定、"
    "已产出的文件与成果(保留文件路径、命令、报错等原文细节)、尚未完成的事项。"
    "保留后续对话需要的上下文,去掉寒暄与冗余。只输出要点本身,不要额外解释。"
    "摘要总长控制在 1500 字以内;与已有摘要合并时优先精简更早的内容,越新的信息保留越多细节。"
)
# 摘要输出上限:1500 字要点绰绰有余;防话痨模型无界输出(输入折叠段可达数万 token)。
_SUMMARIZE_MAX_TOKENS = 2048


def _build_context_and_history(
    request: worker_pb2.RunTurnRequest,
    network_region: str = "",
    web_search_available: bool = False,
    tz_offset_hours: float = 8.0,
) -> tuple[str, list]:
    # 现算"今天日期"(指定时区),注入 system prompt——模型不知真实日期,查时事会瞎猜。
    # 星期用固定英文查表(不用 strftime %A:那依赖进程 locale,不同环境可能输出非英文/乱码)。
    now = datetime.now(timezone(timedelta(hours=tz_offset_hours)))
    weekday = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[
        now.weekday()
    ]
    current_date = f"{now:%Y-%m-%d} ({weekday})"
    system = build_system_prompt(
        documents=[ContextDocument(d.scope, d.type, d.content) for d in request.documents],
        memory=[MemoryItem(m.scope, m.content) for m in request.memory],
        skills=[SkillRef(s.name, s.description, s.location) for s in request.skills],
        history_summary=request.history_summary,
        network_region=network_region,
        web_search_available=web_search_available,
        current_date=current_date,
    )
    history = [msg_from_proto(m) for m in request.messages]
    return system, history


class WorkerServicer(worker_pb2_grpc.WorkerServicer):
    def __init__(
        self,
        provider_factory: ProviderFactory,
        network_region: str = "",
        max_iterations: int = 20,
        *,
        timezone_offset_hours: float = 8.0,
        web_search_endpoint: str = DEFAULT_SEARCH_ENDPOINT,
        web_search_api_key: str = "",
        web_search_max_results: int = 8,
        image_gen_endpoint: str = DEFAULT_IMAGE_ENDPOINT,
        image_gen_api_key: str = "",
        image_gen_model: str = DEFAULT_IMAGE_MODEL,
        image_edit_model: str = DEFAULT_IMAGE_EDIT_MODEL,
    ) -> None:
        self._provider_factory = provider_factory
        self._network_region = network_region
        self._max_iterations = max_iterations
        self._timezone_offset_hours = timezone_offset_hours
        self._web_search_endpoint = web_search_endpoint
        self._web_search_api_key = web_search_api_key
        self._web_search_max_results = web_search_max_results
        self._image_gen_endpoint = image_gen_endpoint
        self._image_gen_api_key = image_gen_api_key
        self._image_gen_model = image_gen_model
        self._image_edit_model = image_edit_model

    def _web_search_available(self) -> bool:
        # 配了搜索 key + 端点才算可用:决定 web_search 是否暴露 + system prompt 搜索段是否指向工具。
        return bool(self._web_search_api_key and self._web_search_endpoint)

    def _image_gen_available(self) -> bool:
        # 配了图片生成 key + 端点才算可用:决定 generate_image 是否暴露(同 web_search,未配降级)。
        return bool(self._image_gen_api_key and self._image_gen_endpoint)

    def _build_executor(self, channel: grpc.aio.Channel, request: worker_pb2.RunTurnRequest):
        """构造本回合的工具执行器(RunTurn / RunTurnStream 共用)。

        分层:ImageGenExecutor(可选) → WebSearchExecutor(可选) → RememberingExecutor →
        SandboxToolExecutor。generate_image / web_search / remember 是 worker 原生(本地处理、
        绝不进沙箱);其余委托沙箱执行。generate_image 拿到图片字节后经 sandbox_exec 的 WriteBinary
        落进工作区。各 worker 原生工具仅在配了对应平台 key 时暴露(独立于 LLM key,未配自动降级)。
        """
        enabled_tools = list(request.agent.enabled_tools)
        sandbox_exec = SandboxToolExecutor(
            channel,
            request.work_subdir,
            enabled_tools,
            token=request.sandbox_token,
        )
        executor = RememberingExecutor(sandbox_exec, enabled=remember_enabled(enabled_tools))
        # 定时任务跑出来的回合(is_scheduled_run)不暴露 schedule_task,防 agent 自我繁殖。
        executor = SchedulingExecutor(
            executor,
            enabled=schedule_task_enabled(enabled_tools) and not request.is_scheduled_run,
        )
        # notify 不按 is_scheduled_run 关闭——定时任务到点提醒正是主用例。按 client 门控:notify
        # 送达浏览器(OS 通知 + 网页弹窗),mobile App 无接收通道,故仅非 mobile 暴露(与下面
        # client_actions 的 mobile-only 相反)。
        executor = NotifyingExecutor(
            executor, enabled=notify_enabled(enabled_tools), client=request.client
        )
        # set_alarm / add_calendar_event:worker 合成确认,真正副作用在用户设备上由 App 执行。
        # 按 client 过滤:仅 mobile 暴露(web 没有系统闹钟/日历执行通道,见 ClientActionsExecutor)。
        executor = ClientActionsExecutor(
            executor, enabled_tools=enabled_tools, client=request.client
        )
        if self._web_search_available():
            searcher = make_sophnet_searcher(
                endpoint=self._web_search_endpoint,
                api_key=self._web_search_api_key,
                max_results=self._web_search_max_results,
            )
            executor = WebSearchExecutor(
                executor, enabled=web_search_enabled(enabled_tools), search_fn=searcher
            )
        if self._image_gen_available():
            generator = make_sophnet_image_generator(
                endpoint=self._image_gen_endpoint,
                api_key=self._image_gen_api_key,
                model=self._image_gen_model,
            )
            executor = ImageGenExecutor(
                executor,
                enabled=generate_image_enabled(enabled_tools),
                generate_fn=generator,
                write_binary_fn=sandbox_exec.write_binary,
            )
            # edit_image:同 key/端点,只换 Edit 模型;读输入图走 sandbox_exec.read_binary。
            editor = make_sophnet_image_generator(
                endpoint=self._image_gen_endpoint,
                api_key=self._image_gen_api_key,
                model=self._image_edit_model,
            )
            executor = ImageEditExecutor(
                executor,
                enabled=edit_image_enabled(enabled_tools),
                generate_fn=editor,
                read_binary_fn=sandbox_exec.read_binary,
                write_binary_fn=sandbox_exec.write_binary,
            )
        return executor, sandbox_exec

    async def RunTurn(
        self, request: worker_pb2.RunTurnRequest, context: grpc.aio.ServicerContext
    ) -> worker_pb2.RunTurnResponse:
        # 解码客户端输入。畸形输入(非法 role / 坏 arguments_json)是 client-fault,
        # 必须映射成 INVALID_ARGUMENT,而不是冒泡成无法与真实 worker bug 区分的 UNKNOWN。
        try:
            system, history = _build_context_and_history(
                request,
                self._network_region,
                self._web_search_available(),
                self._timezone_offset_hours,
            )
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
            executor, sandbox_exec = self._build_executor(channel, request)
            user_images = await _read_turn_images(sandbox_exec.read_binary, request.turn_images)
            try:
                result = await run_turn(
                    provider,
                    executor,
                    system=system,
                    history=history,
                    user_message=request.user_message,
                    user_images=user_images,
                    max_iterations=self._max_iterations,
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
            system, history = _build_context_and_history(
                request,
                self._network_region,
                self._web_search_available(),
                self._timezone_offset_hours,
            )
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
            executor, sandbox_exec = self._build_executor(channel, request)
            # subagent:最外层包 SubagentExecutor(暴露 task;inner 是完整工具链不含 task → 封顶 1)。
            # emit 队列让子 agent 事件流回 run_turn_stream 的工具执行处穿插透传(仅流式路径接入)。
            emit_queue: asyncio.Queue = asyncio.Queue()
            subagent_exec: SubagentExecutor | None = None
            if subagent_enabled(list(request.agent.enabled_tools)):
                subagent_exec = SubagentExecutor(
                    executor, provider, emit_queue, max_iterations=self._max_iterations
                )
                executor = subagent_exec
            user_images = await _read_turn_images(sandbox_exec.read_binary, request.turn_images)
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
                    user_images=user_images,
                    max_iterations=self._max_iterations,
                    emit=emit_queue,
                ):
                    if isinstance(event, _Tagged):
                        yield turn_event_to_proto(event.event, event.subagent_id)
                        continue
                    # 主回合收尾:把子 agent 累计 usage 并入总 usage(token 计费),并把子 agent
                    # 过程消息(带 parent_call_id)并入 new_messages 一起落库(供前端刷新后重建)。
                    if isinstance(event, TurnDone) and subagent_exec is not None:
                        event.usage = Usage(
                            input_tokens=event.usage.input_tokens
                            + subagent_exec.accumulated_usage.input_tokens,
                            output_tokens=event.usage.output_tokens
                            + subagent_exec.accumulated_usage.output_tokens,
                        )
                        event.new_messages = [
                            *event.new_messages,
                            *subagent_exec.accumulated_sub_messages,
                        ]
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

    async def Terminal(self, request_iterator, context: grpc.aio.ServicerContext):
        # 纯透传桥:backend→worker→sandbox。sandbox 连接信息走 gRPC metadata
        # (不进消息体、不回前端)。双向泵:client→sandbox、sandbox→client。
        md = dict(context.invocation_metadata() or ())
        endpoint = md.get("x-sandbox-endpoint", "")
        token = md.get("x-sandbox-token", "")
        if not endpoint:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "missing sandbox endpoint")
        options = [
            ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
            ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
        ]
        async with grpc.aio.insecure_channel(endpoint, options=options) as ch:
            # 等沙箱 server 就绪再开流:首次 spawn 的沙箱 server 冷启动(容器已起但 gRPC 还没
            # 监听)时,worker 立刻连会 Connection refused → 终端秒断。channel_ready 会重试
            # 连接直到就绪或超时(此处只用于建连阶段,不限制随后的长流时长)。
            try:
                await asyncio.wait_for(ch.channel_ready(), timeout=15)
            except (TimeoutError, grpc.aio.AioRpcError):
                await context.abort(grpc.StatusCode.UNAVAILABLE, "sandbox not ready")
                return
            sbx = sandbox_pb2_grpc.SandboxStub(ch)
            sbx_call = sbx.Terminal(metadata=(("x-sandbox-token", token),))

            async def _forward_in() -> None:
                try:
                    async for msg in request_iterator:
                        await sbx_call.write(msg)
                finally:
                    await sbx_call.done_writing()

            fwd = asyncio.create_task(_forward_in())
            try:
                async for out in sbx_call:
                    yield out
            finally:
                fwd.cancel()

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
                # 关思考 + 收紧输出:思考模型(DeepSeek-V4-Pro)会为摘要烧大段 reasoning
                # (慢且贵,同标题生成踩过的坑);max_tokens 防摘要无界增长(见 _SUMMARIZE_SYSTEM)。
                CompletionRequest(
                    system=system,
                    messages=messages,
                    tools=[],
                    max_tokens=_SUMMARIZE_MAX_TOKENS,
                    disable_thinking=True,
                )
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
                    max_tokens=64,  # 关思考后几个字标题足够
                    # 关思考:DeepSeek-V4-Pro 等思考型模型否则把 token 全烧在 reasoning、content
                    # 空 → 标题恒空(实测)。标题任务不需要思考,enable_thinking=false 直接出结果。
                    disable_thinking=True,
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
    provider_factory: ProviderFactory,
    host: str = "localhost",
    port: int = 0,
    network_region: str = "",
    max_iterations: int = 20,
    timezone_offset_hours: float = 8.0,
    web_search_endpoint: str = DEFAULT_SEARCH_ENDPOINT,
    web_search_api_key: str = "",
    web_search_max_results: int = 8,
    image_gen_endpoint: str = DEFAULT_IMAGE_ENDPOINT,
    image_gen_api_key: str = "",
    image_gen_model: str = DEFAULT_IMAGE_MODEL,
    image_edit_model: str = DEFAULT_IMAGE_EDIT_MODEL,
) -> tuple[grpc.aio.Server, int]:
    server = grpc.aio.server(
        options=[
            ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
            ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
        ]
    )
    worker_pb2_grpc.add_WorkerServicer_to_server(
        WorkerServicer(
            provider_factory,
            network_region=network_region,
            max_iterations=max_iterations,
            timezone_offset_hours=timezone_offset_hours,
            web_search_endpoint=web_search_endpoint,
            web_search_api_key=web_search_api_key,
            web_search_max_results=web_search_max_results,
            image_gen_endpoint=image_gen_endpoint,
            image_gen_api_key=image_gen_api_key,
            image_gen_model=image_gen_model,
            image_edit_model=image_edit_model,
        ),
        server,
    )
    bound_port = server.add_insecure_port(f"{host}:{port}")
    await server.start()
    return server, bound_port
