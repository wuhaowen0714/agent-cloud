import json

import httpx
import pytest
from agent_cloud_common import ToolCall, ToolResult, ToolSpec
from agent_cloud_worker.image_gen import (
    GENERATE_IMAGE_SPEC,
    ImageGenExecutor,
    generate_image_enabled,
    make_sophnet_image_generator,
)

_ENDPOINT = "https://sophnet.test/imagegenerator/task"
_IMG_URL = "https://oss.test/out/img.png"
# 含非 UTF-8 字节的真二进制:验证字节透传不被当文本损坏。
_PNG = b"\x89PNG\r\n\x1a\n\x00\xff\xfe\xfdpixels\x00"


async def _nosleep(_seconds: float) -> None:
    return None


async def _fake_generate(prompt, size=None, negative_prompt=None) -> bytes:
    return _PNG


async def _fake_write(path: str, data: bytes) -> str:
    return path


class _FakeInner:
    """内层 executor 替身:有自己的 specs,execute 记录被转发的调用。"""

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def specs(self) -> list[ToolSpec]:
        return [ToolSpec(name="bash", description="", input_schema={})]

    async def execute(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        return ToolResult(call_id=call.id, content="inner-handled", is_error=False)


# --- enabled / spec gating ---


def test_generate_image_enabled_helper():
    assert generate_image_enabled([]) is True  # 空 = 全含(与 bash/web_search 一致)
    assert generate_image_enabled(["generate_image"]) is True
    assert generate_image_enabled(["bash"]) is False


def test_spec_requires_prompt():
    assert GENERATE_IMAGE_SPEC.name == "generate_image"
    assert "prompt" in GENERATE_IMAGE_SPEC.input_schema["required"]


def test_spec_appended_when_enabled():
    ex = ImageGenExecutor(
        _FakeInner(), enabled=True, generate_fn=_fake_generate, write_binary_fn=_fake_write
    )
    names = [s.name for s in ex.specs()]
    assert "bash" in names and "generate_image" in names


def test_spec_hidden_when_disabled():
    ex = ImageGenExecutor(
        _FakeInner(), enabled=False, generate_fn=_fake_generate, write_binary_fn=_fake_write
    )
    names = [s.name for s in ex.specs()]
    assert "generate_image" not in names and "bash" in names


# --- ImageGenExecutor 行为 ---


async def test_generates_and_saves_to_workspace():
    saved: dict = {}

    async def capture_write(path: str, data: bytes) -> str:
        saved["path"] = path
        saved["data"] = data
        return path

    ex = ImageGenExecutor(
        _FakeInner(),
        enabled=True,
        generate_fn=_fake_generate,
        write_binary_fn=capture_write,
        id_fn=lambda: "abc123",
    )
    res = await ex.execute(ToolCall(id="c1", name="generate_image", arguments={"prompt": "a cat"}))
    assert res.is_error is False
    # 落盘到 media/picture/,文件名带 id,字节原样透传
    assert saved["path"] == "media/picture/img_abc123.png"
    assert saved["data"] == _PNG
    # content 含路径,供前端解析渲染
    assert "media/picture/img_abc123.png" in res.content


async def test_delegates_non_generate_image_to_inner():
    inner = _FakeInner()
    ex = ImageGenExecutor(
        inner, enabled=True, generate_fn=_fake_generate, write_binary_fn=_fake_write
    )
    res = await ex.execute(ToolCall(id="c2", name="bash", arguments={"command": "ls"}))
    assert res.content == "inner-handled"
    assert len(inner.calls) == 1


async def test_empty_prompt_is_error():
    ex = ImageGenExecutor(
        _FakeInner(), enabled=True, generate_fn=_fake_generate, write_binary_fn=_fake_write
    )
    res = await ex.execute(ToolCall(id="c3", name="generate_image", arguments={"prompt": "  "}))
    assert res.is_error is True
    assert "prompt" in res.content


async def test_disabled_call_is_error():
    # enabled=False 时即使模型硬调也拒绝(可信侧强制,非仅隐藏)
    ex = ImageGenExecutor(
        _FakeInner(), enabled=False, generate_fn=_fake_generate, write_binary_fn=_fake_write
    )
    res = await ex.execute(ToolCall(id="c4", name="generate_image", arguments={"prompt": "x"}))
    assert res.is_error is True


async def test_generate_failure_becomes_is_error():
    async def boom(prompt, size=None, negative_prompt=None):
        raise httpx.ConnectTimeout("timeout")

    ex = ImageGenExecutor(_FakeInner(), enabled=True, generate_fn=boom, write_binary_fn=_fake_write)
    res = await ex.execute(ToolCall(id="c5", name="generate_image", arguments={"prompt": "x"}))
    assert res.is_error is True
    assert "generate_image failed" in res.content


async def test_write_failure_becomes_is_error():
    async def boom_write(path: str, data: bytes) -> str:
        raise RuntimeError("disk full")

    ex = ImageGenExecutor(
        _FakeInner(), enabled=True, generate_fn=_fake_generate, write_binary_fn=boom_write
    )
    res = await ex.execute(ToolCall(id="c6", name="generate_image", arguments={"prompt": "x"}))
    assert res.is_error is True
    assert "failed to save image" in res.content


# --- make_sophnet_image_generator(POST 建任务 → 轮询 → 下载)---


def _make_handler(
    *, running_polls=1, succeed=True, with_url=True, fail_status=None, created_ok=True
):
    """按 (method,url) 路由:POST 建任务、GET 查询(前 running_polls 次 RUNNING)、GET 下载图。"""
    state = {"polls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url == _ENDPOINT:
            if not created_ok:
                return httpx.Response(200, json={"code": "Q", "message": "quota exceeded"})
            return httpx.Response(
                200, json={"output": {"taskId": "img-1", "taskStatus": "PENDING"}}
            )
        if request.method == "GET" and url == f"{_ENDPOINT}/img-1":
            state["polls"] += 1
            if fail_status:
                return httpx.Response(
                    200, json={"output": {"taskStatus": fail_status, "message": "boom"}}
                )
            if state["polls"] <= running_polls or not succeed:
                return httpx.Response(200, json={"output": {"taskStatus": "RUNNING"}})
            results = [{"url": _IMG_URL, "orig_prompt": "p"}] if with_url else []
            return httpx.Response(
                200, json={"output": {"taskStatus": "SUCCEEDED", "results": results}}
            )
        if request.method == "GET" and url == _IMG_URL:
            return httpx.Response(200, content=_PNG)
        return httpx.Response(404, json={"error": f"unexpected {request.method} {url}"})

    return handler


async def test_image_generator_full_flow_builds_request():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url == _ENDPOINT:
            captured["auth"] = request.headers.get("authorization")
            captured["body"] = json.loads(request.content.decode())
            return httpx.Response(
                200, json={"output": {"taskId": "img-1", "taskStatus": "PENDING"}}
            )
        if request.method == "GET" and url == f"{_ENDPOINT}/img-1":
            return httpx.Response(
                200,
                json={"output": {"taskStatus": "SUCCEEDED", "results": [{"url": _IMG_URL}]}},
            )
        return httpx.Response(200, content=_PNG)

    gen = make_sophnet_image_generator(
        endpoint=_ENDPOINT,
        api_key="sk-img",
        model="Qwen-Image",
        transport=httpx.MockTransport(handler),
        sleep=_nosleep,
    )
    data = await gen("a calico cat", "1328*1328", "blurry")
    assert data == _PNG  # 下载的原始字节透传
    assert captured["auth"] == "Bearer sk-img"  # 专用 key,非 LLM key
    assert captured["body"]["model"] == "Qwen-Image"
    assert captured["body"]["input"]["prompt"] == "a calico cat"
    assert captured["body"]["input"]["negative_prompt"] == "blurry"
    assert captured["body"]["parameters"]["size"] == "1328*1328"


async def test_image_generator_omits_optional_params():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST":
            captured["body"] = json.loads(request.content.decode())
            return httpx.Response(
                200, json={"output": {"taskId": "img-1", "taskStatus": "PENDING"}}
            )
        if url == f"{_ENDPOINT}/img-1":
            return httpx.Response(
                200,
                json={"output": {"taskStatus": "SUCCEEDED", "results": [{"url": _IMG_URL}]}},
            )
        return httpx.Response(200, content=_PNG)

    gen = make_sophnet_image_generator(
        endpoint=_ENDPOINT, api_key="k", transport=httpx.MockTransport(handler), sleep=_nosleep
    )
    await gen("just a prompt")
    assert "parameters" not in captured["body"]
    assert "negative_prompt" not in captured["body"]["input"]


async def test_image_generator_polls_until_succeeded():
    gen = make_sophnet_image_generator(
        endpoint=_ENDPOINT,
        api_key="k",
        transport=httpx.MockTransport(_make_handler(running_polls=3, succeed=True)),
        sleep=_nosleep,
    )
    assert await gen("x") == _PNG


async def test_image_generator_raises_on_task_failed():
    gen = make_sophnet_image_generator(
        endpoint=_ENDPOINT,
        api_key="k",
        transport=httpx.MockTransport(_make_handler(fail_status="FAILED")),
        sleep=_nosleep,
    )
    with pytest.raises(RuntimeError, match="FAILED"):
        await gen("x")


async def test_image_generator_raises_on_create_error_envelope():
    gen = make_sophnet_image_generator(
        endpoint=_ENDPOINT,
        api_key="k",
        transport=httpx.MockTransport(_make_handler(created_ok=False)),
        sleep=_nosleep,
    )
    with pytest.raises(RuntimeError, match="quota exceeded"):
        await gen("x")


async def test_image_generator_raises_when_no_url():
    gen = make_sophnet_image_generator(
        endpoint=_ENDPOINT,
        api_key="k",
        transport=httpx.MockTransport(_make_handler(running_polls=0, with_url=False)),
        sleep=_nosleep,
    )
    with pytest.raises(RuntimeError, match="no image url"):
        await gen("x")


async def test_image_generator_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    gen = make_sophnet_image_generator(
        endpoint=_ENDPOINT, api_key="bad", transport=httpx.MockTransport(handler), sleep=_nosleep
    )
    with pytest.raises(httpx.HTTPStatusError):
        await gen("x")


async def test_image_generator_times_out():
    # 任务一直 RUNNING:轮询到 poll_max_seconds 仍未终态 → 报超时。注入假时钟:sleep 推进它、
    # deadline 据它判定(不真等),验证有界退出且不无限循环(deadline 改单调钟后必须靠时钟推进)。
    clock = {"t": 0.0}

    async def advancing_sleep(seconds: float) -> None:
        clock["t"] += seconds

    gen = make_sophnet_image_generator(
        endpoint=_ENDPOINT,
        api_key="k",
        transport=httpx.MockTransport(_make_handler(succeed=False)),
        sleep=advancing_sleep,
        now=lambda: clock["t"],
        poll_interval=1.0,
        poll_max_seconds=3.0,
    )
    with pytest.raises(RuntimeError, match="did not finish"):
        await gen("x")
