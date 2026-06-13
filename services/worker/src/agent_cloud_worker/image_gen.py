from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable

import httpx
from agent_cloud_common import ToolCall, ToolResult, ToolSpec

from agent_cloud_worker.tools import ToolExecutor

# sophnet 图片生成端点(异步任务式:POST 建任务 → GET {endpoint}/{taskId} 轮询直到 SUCCEEDED)。
# config 默认 + server 直接构造的默认都引用它,避免多处硬编码漂移。
DEFAULT_IMAGE_ENDPOINT = (
    "https://www.sophnet.com/api/open-apis/projects/easyllms/imagegenerator/task"
)
DEFAULT_IMAGE_MODEL = "Qwen-Image"

# 落盘子目录(相对工作区)。前端按此路径用 /files/raw 取图渲染。
_IMAGE_SUBDIR = "media/picture"

# generate_image 工具(worker 原生:调外部图片生成 API,**绝不进沙箱**——生成 key 不下放最小信任
# 的沙箱)。端点是 sophnet,用独立于 LLM 的专用 key(同 web_search:用户可能 BYOK 别家模型,其
# key 对 sophnet 无效)。图片落进工作区 media/picture/ 后路径回填给模型,前端据此渲染。
GENERATE_IMAGE_SPEC = ToolSpec(
    name="generate_image",
    description=(
        "Generate an image from a text prompt (text-to-image) and save it into the workspace. "
        "Use this when the user asks you to create, draw, design, or illustrate a picture. "
        "Describe the desired image in detail in 'prompt' (subject, style, lighting, composition). "
        "The image is saved under media/picture/ in the working directory and shown to the user "
        "automatically as soon as it is generated. Do NOT embed it again in your reply with "
        "markdown image syntax such as ![](path), and do NOT paste the file path — it is already "
        "displayed to the user; just briefly describe the image in words. This does NOT edit "
        "existing images."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": (
                    "Detailed description of the image to generate, e.g. 'a calico cat "
                    "astronaut floating in space, cinematic lighting, digital art'."
                ),
            },
            "negative_prompt": {
                "type": "string",
                "description": (
                    "Optional. What to avoid in the image (e.g. 'blurry, text, watermark')."
                ),
            },
            "size": {
                "type": "string",
                "description": (
                    "Optional resolution as WIDTH*HEIGHT, e.g. '1328*1328' (default) or '1664*928'."
                ),
            },
        },
        "required": ["prompt"],
    },
)


def generate_image_enabled(enabled_tools: list[str]) -> bool:
    """空 enabled_tools = 全部(含 generate_image),与其它工具一致;否则需显式列出。"""
    return not enabled_tools or "generate_image" in enabled_tools


# (prompt, size|None, negative_prompt|None) -> 下载好的图片字节;失败抛异常,由 executor 收敛。
ImageGenFn = Callable[[str, str | None, str | None], Awaitable[bytes]]
# (rel_path, data) -> 实际写入的相对路径;失败抛异常。
WriteBinaryFn = Callable[[str, bytes], Awaitable[str]]

_TERMINAL_FAIL = ("FAILED", "CANCELED", "UNKNOWN")

# 瞬时网络错误:端点在 Anti-DDoS 清洗中心后(www.sophnet.com → aliyunddos*),偶发丢 SYN /
# 读超时 / 连接池超时,握手层失败但下次多半成功 → 值得重试。HTTPStatusError(401/配额)【不】
# 在此列:业务错误应快速失败,不重试。
_TRANSIENT_NET = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


def _headers(api_key: str) -> dict:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {api_key}",
    }


def make_sophnet_image_generator(
    *,
    endpoint: str,
    api_key: str,
    model: str = DEFAULT_IMAGE_MODEL,
    timeout: float = 30.0,
    connect_timeout: float = 10.0,
    attempts: int = 3,
    retry_backoff: float = 1.5,
    poll_interval: float = 2.5,
    poll_max_seconds: float = 180.0,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    now: Callable[[], float] | None = None,
) -> ImageGenFn:
    """造一个调 sophnet 图片生成端点的 ImageGenFn:POST 建任务 → 轮询 → 下载图片字节。

    Bearer = 平台专用 key(独立于 LLM key)。建任务 / 下载图这两步对瞬时网络错误重试 ``attempts``
    次(指数退避 ``retry_backoff``);连接超时单独压到 ``connect_timeout``(默认 10s)让失败快速触发
    重试而非干等。transport/sleep/now 仅供测试注入(MockTransport / 假 sleep 跳过真实等待 / 假时钟
    驱动 deadline);生产传 None 用默认网络栈、asyncio.sleep、单调钟。
    """
    _sleep = sleep or asyncio.sleep
    _now = now or time.monotonic

    async def generate(
        prompt: str, size: str | None = None, negative_prompt: str | None = None
    ) -> bytes:
        input_obj: dict = {"prompt": prompt}
        if negative_prompt:
            input_obj["negative_prompt"] = negative_prompt
        payload: dict = {"model": model, "input": input_obj}
        if size:
            payload["parameters"] = {"size": size}

        # 连接超时单列、短于整体 timeout:Anti-DDoS 丢 SYN 时不干等满 timeout 才重试。
        timeout_cfg = httpx.Timeout(timeout, connect=connect_timeout)
        async with httpx.AsyncClient(
            timeout=timeout_cfg, transport=transport, follow_redirects=True
        ) as client:

            async def _send(do: Callable[[], Awaitable[httpx.Response]]) -> httpx.Response:
                """对瞬时网络错误重试 attempts 次(指数退避);HTTPStatusError 等立即抛(不重试)。"""
                last: Exception | None = None
                for i in range(attempts):
                    try:
                        return await do()
                    except _TRANSIENT_NET as exc:
                        last = exc
                        if i + 1 < attempts:
                            await _sleep(retry_backoff * (i + 1))
                if last is not None:
                    raise last
                raise RuntimeError("image request made no attempts")  # attempts<1,不该发生

            # 1. 建任务(返回 taskId + 通常 PENDING)。瞬时连接错误重试(连接未建立 → 重试安全)。
            async def _create() -> httpx.Response:
                r = await client.post(
                    endpoint,
                    headers=_headers(api_key),
                    content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                )
                r.raise_for_status()
                return r

            resp = await _send(_create)
            created = resp.json()
            if not isinstance(created, dict):
                raise RuntimeError("image backend returned an unexpected payload")
            out = created.get("output") or {}
            task_id = out.get("taskId")
            if not task_id:
                # 错误信封:HTTP 200 但无 output.taskId(配额/限流/key 失效等)。message 是服务端
                # 文案、不含 key,可安全外带给模型。
                detail = created.get("message") or created.get("code") or "no taskId returned"
                raise RuntimeError(f"image backend error: {detail}")

            # 2. 轮询查询任务,直到终态。deadline 用单调钟(含每次 GET 的耗时);只累加 sleep 会在
            # 慢端点下把名义 180s 拖到数十分钟,且错误信息撒谎(实际远超 poll_max_seconds 才报)。
            query_url = f"{endpoint}/{task_id}"
            deadline = _now() + poll_max_seconds
            final: dict | None = None
            while _now() < deadline:
                await _sleep(poll_interval)
                try:
                    q = await client.get(query_url, headers=_headers(api_key))
                    q.raise_for_status()
                except _TRANSIENT_NET:
                    continue  # 轮询中途瞬时抖动:本轮跳过,deadline 内下轮再查(不中止任务)
                qd = q.json()
                qout = (qd or {}).get("output") or {}
                status = qout.get("taskStatus")
                if status == "SUCCEEDED":
                    final = qout
                    break
                if status in _TERMINAL_FAIL:
                    detail = qout.get("message") or (qd or {}).get("message") or status
                    raise RuntimeError(f"image task {status}: {detail}")
                # PENDING / RUNNING / 缺失 → 继续轮询
            if final is None:
                raise RuntimeError(
                    f"image generation did not finish within {poll_max_seconds:.0f}s"
                )

            # 3. 取首图 url 并下载原始字节
            results = final.get("results") or []
            url = next(
                (r.get("url") for r in results if isinstance(r, dict) and r.get("url")), None
            )
            if not url:
                raise RuntimeError("image task succeeded but returned no image url")

            # 3b. 下载原始字节(瞬时连接错误重试:OSS/CDN 偶发抖动)
            async def _download() -> httpx.Response:
                r = await client.get(url)
                r.raise_for_status()
                return r

            img = await _send(_download)
            return img.content

    return generate


class ImageGenExecutor:
    """装饰 ToolExecutor:加 worker 原生的 ``generate_image`` 工具(文生图)。

    调外部图片生成 API(平台专用 key),在 worker 处理、**绝不把 key 进沙箱**;拿到图片字节后经
    沙箱 WriteBinary RPC 落进工作区 media/picture/,返回相对路径。其余工具委托内层 executor。
    失败(HTTP/超时/任务失败/落盘)收敛成 is_error 结果,不让异常冲掉整个回合。
    """

    def __init__(
        self,
        inner: ToolExecutor,
        *,
        enabled: bool,
        generate_fn: ImageGenFn,
        write_binary_fn: WriteBinaryFn,
        id_fn: Callable[[], str] | None = None,
    ) -> None:
        self._inner = inner
        self._enabled = enabled
        self._generate_fn = generate_fn
        self._write_binary_fn = write_binary_fn
        # 文件名 id 生成器(可注入便于测试断言精确路径);默认 uuid4 短 hex。
        self._id_fn = id_fn or (lambda: uuid.uuid4().hex[:12])

    def specs(self) -> list[ToolSpec]:
        specs = list(self._inner.specs())
        if self._enabled:
            specs.append(GENERATE_IMAGE_SPEC)
        return specs

    async def execute(self, call: ToolCall) -> ToolResult:
        if call.name != "generate_image":
            return await self._inner.execute(call)
        # 可信侧强制启用判定(与 web_search/remember 一致,防 skill 等不可信内容诱导)。
        if not self._enabled:
            return ToolResult(
                call_id=call.id, content="tool not enabled: generate_image", is_error=True
            )
        args = call.arguments or {}
        prompt = args.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return ToolResult(
                call_id=call.id,
                content="generate_image: 'prompt' (non-empty string) is required",
                is_error=True,
            )
        size = args.get("size")
        size = size.strip() if isinstance(size, str) and size.strip() else None
        negative = args.get("negative_prompt")
        negative = negative.strip() if isinstance(negative, str) and negative.strip() else None

        try:
            data = await self._generate_fn(prompt.strip(), size, negative)
        except Exception as exc:  # noqa: BLE001 — HTTP/超时/任务失败转 is_error,让模型换路
            return ToolResult(
                call_id=call.id,
                content=f"generate_image failed: {type(exc).__name__}: {exc}",
                is_error=True,
            )
        rel_path = f"{_IMAGE_SUBDIR}/img_{self._id_fn()}.png"
        try:
            written = await self._write_binary_fn(rel_path, data)
        except Exception as exc:  # noqa: BLE001 — 落盘失败也收敛成 is_error
            return ToolResult(
                call_id=call.id,
                content=f"generate_image: failed to save image: {type(exc).__name__}: {exc}",
                is_error=True,
            )
        # content 既给模型读,也供前端解析路径渲染图(前端按 call.name==generate_image 提路径)。
        return ToolResult(
            call_id=call.id,
            content=(
                f"Image generated and shown to the user (saved at {written}). It is already "
                "displayed — do not embed it again or repeat the path in your reply."
            ),
            is_error=False,
        )
