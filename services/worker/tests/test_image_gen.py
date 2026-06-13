import json

import httpx
import pytest
from agent_cloud_common import ToolCall, ToolResult, ToolSpec
from agent_cloud_worker.image_gen import (
    EDIT_IMAGE_SPEC,
    GENERATE_IMAGE_SPEC,
    ImageEditExecutor,
    ImageGenExecutor,
    _slugify,
    edit_image_enabled,
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
    # 落盘到 media/picture/,文件名 = prompt 语义 slug + 短 id,字节原样透传
    assert saved["path"] == "media/picture/a-cat-abc123.png"
    assert saved["data"] == _PNG
    # content 含路径(供前端解析渲染)+ 明确"已展示、勿重复"(防模型在正文再插一个坏 markdown 图)
    assert "media/picture/a-cat-abc123.png" in res.content
    assert "do not embed it again" in res.content


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


async def test_image_generator_retries_transient_connect_on_post():
    """POST 建任务首次 ConnectTimeout(Anti-DDoS 偶发丢 SYN),重试后成功 → 仍返回图片。"""
    state = {"posts": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url == _ENDPOINT:
            state["posts"] += 1
            if state["posts"] == 1:
                raise httpx.ConnectTimeout("transient", request=request)
            return httpx.Response(
                200, json={"output": {"taskId": "img-1", "taskStatus": "PENDING"}}
            )
        if request.method == "GET" and url == f"{_ENDPOINT}/img-1":
            return httpx.Response(
                200, json={"output": {"taskStatus": "SUCCEEDED", "results": [{"url": _IMG_URL}]}}
            )
        if request.method == "GET" and url == _IMG_URL:
            return httpx.Response(200, content=_PNG)
        return httpx.Response(404)

    gen = make_sophnet_image_generator(
        endpoint=_ENDPOINT, api_key="k", transport=httpx.MockTransport(handler), sleep=_nosleep
    )
    assert await gen("x") == _PNG
    assert state["posts"] == 2  # 第一次失败、第二次成功


async def test_image_generator_gives_up_after_retries():
    """POST 持续 ConnectTimeout:重试耗尽后抛出(不无限重试)。"""
    state = {"posts": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            state["posts"] += 1
            raise httpx.ConnectTimeout("always", request=request)
        return httpx.Response(404)

    gen = make_sophnet_image_generator(
        endpoint=_ENDPOINT,
        api_key="k",
        transport=httpx.MockTransport(handler),
        sleep=_nosleep,
        attempts=3,
    )
    with pytest.raises(httpx.ConnectTimeout):
        await gen("x")
    assert state["posts"] == 3  # 恰好 attempts 次


async def test_image_generator_retries_transient_on_download():
    """下载图字节首次 ConnectError,重试后成功。"""
    state = {"dl": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url == _ENDPOINT:
            return httpx.Response(
                200, json={"output": {"taskId": "img-1", "taskStatus": "PENDING"}}
            )
        if request.method == "GET" and url == f"{_ENDPOINT}/img-1":
            return httpx.Response(
                200, json={"output": {"taskStatus": "SUCCEEDED", "results": [{"url": _IMG_URL}]}}
            )
        if request.method == "GET" and url == _IMG_URL:
            state["dl"] += 1
            if state["dl"] == 1:
                raise httpx.ConnectError("transient", request=request)
            return httpx.Response(200, content=_PNG)
        return httpx.Response(404)

    gen = make_sophnet_image_generator(
        endpoint=_ENDPOINT, api_key="k", transport=httpx.MockTransport(handler), sleep=_nosleep
    )
    assert await gen("x") == _PNG
    assert state["dl"] == 2


async def test_image_generator_poll_survives_transient_blip():
    """轮询中途一次瞬时网络抖动不应中止整个任务,下一轮继续直到 SUCCEEDED。"""
    state = {"polls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url == _ENDPOINT:
            return httpx.Response(
                200, json={"output": {"taskId": "img-1", "taskStatus": "PENDING"}}
            )
        if request.method == "GET" and url == f"{_ENDPOINT}/img-1":
            state["polls"] += 1
            if state["polls"] == 1:
                raise httpx.ReadTimeout("blip", request=request)  # 第一轮抖动
            return httpx.Response(
                200, json={"output": {"taskStatus": "SUCCEEDED", "results": [{"url": _IMG_URL}]}}
            )
        if request.method == "GET" and url == _IMG_URL:
            return httpx.Response(200, content=_PNG)
        return httpx.Response(404)

    gen = make_sophnet_image_generator(
        endpoint=_ENDPOINT,
        api_key="k",
        transport=httpx.MockTransport(handler),
        sleep=_nosleep,
        poll_interval=0.1,
        poll_max_seconds=30.0,
    )
    assert await gen("x") == _PNG
    assert state["polls"] == 2  # 第一轮抖动被吞、第二轮成功


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


# --- edit_image / ImageEditExecutor ---


async def _fake_read(path: str) -> bytes:
    return _PNG


async def _fake_generate_edit(prompt, size=None, negative_prompt=None, images=None) -> bytes:
    return _PNG


def _edit_ex(
    inner=None,
    *,
    enabled=True,
    read_fn=_fake_read,
    gen_fn=_fake_generate_edit,
    write_fn=_fake_write,
    id_fn=lambda: "e1",
):
    return ImageEditExecutor(
        inner or _FakeInner(),
        enabled=enabled,
        generate_fn=gen_fn,
        read_binary_fn=read_fn,
        write_binary_fn=write_fn,
        id_fn=id_fn,
    )


def test_edit_image_enabled_helper():
    assert edit_image_enabled([]) is True
    assert edit_image_enabled(["edit_image"]) is True
    assert edit_image_enabled(["bash"]) is False


def test_edit_spec_requires_paths_and_prompt():
    assert EDIT_IMAGE_SPEC.name == "edit_image"
    req = EDIT_IMAGE_SPEC.input_schema["required"]
    assert "image_paths" in req and "prompt" in req


def test_edit_spec_gating():
    assert "edit_image" in [s.name for s in _edit_ex(enabled=True).specs()]
    assert "edit_image" not in [s.name for s in _edit_ex(enabled=False).specs()]


async def test_edit_reads_input_and_saves():
    seen: dict = {}

    async def capture_read(path):
        seen.setdefault("reads", []).append(path)
        return _PNG

    async def capture_gen(prompt, size=None, negative_prompt=None, images=None):
        seen["images"] = images
        seen["prompt"] = prompt
        return _PNG

    saved: dict = {}

    async def capture_write(path, data):
        saved["path"] = path
        saved["data"] = data
        return path

    ex = _edit_ex(read_fn=capture_read, gen_fn=capture_gen, write_fn=capture_write)
    res = await ex.execute(
        ToolCall(
            id="c",
            name="edit_image",
            arguments={"image_paths": ["media/upload/a.png"], "prompt": "make it blue"},
        )
    )
    assert res.is_error is False
    assert seen["reads"] == ["media/upload/a.png"]
    # 输入图被读出 base64 data URI 喂给 sophnet input.images
    assert len(seen["images"]) == 1
    assert seen["images"][0].startswith("data:image/png;base64,")
    assert seen["prompt"] == "make it blue"
    assert saved["path"] == "media/picture/edited-make-it-blue-e1.png"
    assert saved["data"] == _PNG
    assert "media/picture/edited-make-it-blue-e1.png" in res.content


async def test_edit_delegates_non_edit_to_inner():
    inner = _FakeInner()
    res = await _edit_ex(inner).execute(
        ToolCall(id="c", name="bash", arguments={"command": "ls"})
    )
    assert res.content == "inner-handled"
    assert len(inner.calls) == 1


async def test_edit_disabled_is_error():
    res = await _edit_ex(enabled=False).execute(
        ToolCall(id="c", name="edit_image", arguments={"image_paths": ["a.png"], "prompt": "x"})
    )
    assert res.is_error is True


async def test_edit_empty_prompt_is_error():
    res = await _edit_ex().execute(
        ToolCall(id="c", name="edit_image", arguments={"image_paths": ["a.png"], "prompt": " "})
    )
    assert res.is_error is True
    assert "prompt" in res.content


async def test_edit_missing_paths_is_error():
    res = await _edit_ex().execute(
        ToolCall(id="c", name="edit_image", arguments={"prompt": "x"})
    )
    assert res.is_error is True
    assert "image_paths" in res.content


async def test_edit_single_string_path_coerced():
    # 模型偶尔传单字符串而非数组 → 容错成 1 张
    seen: dict = {}

    async def capture_read(path):
        seen["path"] = path
        return _PNG

    res = await _edit_ex(read_fn=capture_read).execute(
        ToolCall(
            id="c",
            name="edit_image",
            arguments={"image_paths": "media/upload/a.png", "prompt": "x"},
        )
    )
    assert res.is_error is False
    assert seen["path"] == "media/upload/a.png"


async def test_edit_too_many_images_is_error():
    res = await _edit_ex().execute(
        ToolCall(
            id="c",
            name="edit_image",
            arguments={"image_paths": ["a", "b", "c", "d"], "prompt": "x"},
        )
    )
    assert res.is_error is True
    assert "at most" in res.content


async def test_edit_read_failure_is_error():
    async def boom_read(path):
        raise RuntimeError("file not found")

    res = await _edit_ex(read_fn=boom_read).execute(
        ToolCall(
            id="c", name="edit_image", arguments={"image_paths": ["nope.png"], "prompt": "x"}
        )
    )
    assert res.is_error is True
    assert "cannot read input image" in res.content


async def test_edit_generate_failure_is_error():
    async def boom_gen(prompt, size=None, negative_prompt=None, images=None):
        raise httpx.ConnectTimeout("timeout")

    res = await _edit_ex(gen_fn=boom_gen).execute(
        ToolCall(id="c", name="edit_image", arguments={"image_paths": ["a.png"], "prompt": "x"})
    )
    assert res.is_error is True
    assert "edit_image failed" in res.content


async def test_edit_write_failure_is_error():
    async def boom_write(path, data):
        raise RuntimeError("disk full")

    res = await _edit_ex(write_fn=boom_write).execute(
        ToolCall(id="c", name="edit_image", arguments={"image_paths": ["a.png"], "prompt": "x"})
    )
    assert res.is_error is True
    assert "failed to save image" in res.content


async def test_image_generator_passes_images_in_payload():
    # make_sophnet_image_generator 传 images → payload.input.images(图生图/编辑链路)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST":
            captured["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"output": {"taskId": "t", "taskStatus": "PENDING"}})
        if url == f"{_ENDPOINT}/t":
            return httpx.Response(
                200,
                json={"output": {"taskStatus": "SUCCEEDED", "results": [{"url": _IMG_URL}]}},
            )
        return httpx.Response(200, content=_PNG)

    gen = make_sophnet_image_generator(
        endpoint=_ENDPOINT,
        api_key="k",
        model="Qwen-Image-Edit-2509",
        transport=httpx.MockTransport(handler),
        sleep=_nosleep,
    )
    await gen("edit it", None, None, images=["data:image/png;base64,AAAA"])
    assert captured["body"]["model"] == "Qwen-Image-Edit-2509"
    assert captured["body"]["input"]["images"] == ["data:image/png;base64,AAAA"]


async def test_edit_total_size_exceeded_is_error(monkeypatch):
    # M1:多图聚合字节超上限 → is_error(防 base64 膨胀后请求体过大 + worker 内存)。
    import agent_cloud_worker.image_gen as ig

    monkeypatch.setattr(ig, "_MAX_TOTAL_EDIT_BYTES", 10)

    async def big_read(path):
        return b"x" * 8  # 每张 8 字节,两张 = 16 > 10

    res = await _edit_ex(read_fn=big_read).execute(
        ToolCall(
            id="c",
            name="edit_image",
            arguments={"image_paths": ["a.png", "b.png"], "prompt": "x"},
        )
    )
    assert res.is_error is True
    assert "total input image size" in res.content


# --- _slugify(图片文件名语义化) ---


def test_slugify_english_to_hyphens():
    assert _slugify("a cat on the beach") == "a-cat-on-the-beach"


def test_slugify_keeps_chinese():
    assert _slugify("一只在冲浪的柴犬") == "一只在冲浪的柴犬"


def test_slugify_strips_path_injection():
    # prompt 是模型内容,绝不能让 ../ 或路径分隔进文件名(sandbox 围栏外的第一道防线)
    s = _slugify("../../etc/passwd")
    assert "/" not in s and ".." not in s and "\\" not in s
    s2 = _slugify('a/b\\c:d*e?f"g<h>i|j')
    assert not (set(s2) & set('/\\:*?"<>|'))


def test_slugify_empty_or_dots_falls_back():
    assert _slugify("") == "image"
    assert _slugify("   ") == "image"
    assert _slugify("...") == "image"


def test_slugify_truncates_long():
    assert len(_slugify("word " * 100)) <= 40


def test_slugify_first_line_only_drops_malicious_second_line():
    assert _slugify("title line\nsecond line") == "title-line"
    assert _slugify("ok\n../../etc/passwd") == "ok"  # 恶意第二行被整段丢弃


def test_slugify_unicode_slash_kept_but_not_ascii_separator():
    # U+FF0F 全角斜杠保留为字符(Linux 只认字节 0x2F 当分隔符),不构成目录穿越
    assert "/" not in _slugify("a／b／c")


def test_slugify_strips_nul_and_control():
    assert _slugify("a\x00b\tc") == "a-b-c"


def test_slugify_truncate_leaves_no_trailing_hyphen():
    s = _slugify("x" * 39 + " " + "y" * 10)  # 第 40 位附近切在连字符处
    assert len(s) <= 40 and not s.endswith("-")
