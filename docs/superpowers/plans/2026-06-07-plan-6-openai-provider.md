# Plan 6: 真实 LLM provider(OpenAI 接口格式)+ worker 入口 + provider 层韧性 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 **OpenAI 接口格式**(OpenAI 兼容的 chat completions 协议,官方 `openai` SDK + `base_url` 覆盖)实现真实 LLM provider,替换 FakeProvider 走通真实回合;补上 worker 的生产入口;在 provider 层做超时/重试/错误映射的韧性加固。

**Architecture:** `OpenAIProvider` 实现既有 `Provider`/`StreamingProvider` 协议(`complete` + `stream`),把领域类型(`CompletionRequest`/`Message`/`ToolSpec` ↔ `CompletionResult`)映射到 OpenAI chat completions 的 messages/tools/tool_calls 格式。用 `AsyncOpenAI(base_url=...)`,因此对接 OpenAI / OpenRouter / vLLM / 本地等**任何 OpenAI 兼容端点**。凭据 v1 走 **env/config**(`key_ref` → 单组 {api_key, base_url};KMS/DB ProviderKeys 留后续)。worker 加 `__main__` 入口,用真实 factory 起 gRPC server。韧性:`openai` SDK 内置 timeout + max_retries(自动退避 429/5xx),provider 失败映射成干净的 gRPC 状态(后端已把它转 502;回合失败但无半成品)。

**Tech Stack:** `openai`(官方异步 SDK)、pydantic-settings、既有 worker gRPC server / run_turn loop、pytest(mock 掉 openai client,不打真实 API)。

**v1 取舍:** 单组凭据(所有 agent 共用配置的 api_key/base_url;每-key_ref 选择 + KMS 留后续);thinking 仅在端点提供 `reasoning_content` 时透传(标准 OpenAI 无 thinking 流)。

---

## 测试约定

- worker / common 套件无 Docker:`cd services/worker && uv run pytest -q --timeout=60`。
- backend 套件(回归):`cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q --timeout=120`(teardown 挂死已在 pre-plan6 修复,可一次跑完)。
- **不打真实 OpenAI API**:所有 provider 测试用 mock 的 `AsyncOpenAI`(注入 fake client)。
- 每条命令显式 `cd` 到对应 service 目录(cwd 跨命令保持)。

## 文件结构

**新建:**
- `services/worker/src/agent_cloud_worker/config.py` — `WorkerSettings`
- `services/worker/src/agent_cloud_worker/openai_provider.py` — 映射函数 + `OpenAIProvider`
- `services/worker/src/agent_cloud_worker/factory.py` — `build_provider_factory`
- `services/worker/src/agent_cloud_worker/__main__.py` — 生产入口
- `services/worker/tests/test_openai_mapping.py`
- `services/worker/tests/test_openai_provider.py`
- `services/worker/tests/test_factory.py`
- `services/worker/tests/test_server_provider_error.py`

**修改:**
- `services/worker/pyproject.toml` — 加 `openai`、`pydantic-settings`
- `services/worker/src/agent_cloud_worker/server.py` — 一元 RunTurn 包错误映射(韧性)
- `services/worker/src/agent_cloud_worker/__init__.py` — 导出 `OpenAIProvider` / `build_provider_factory`(可选)

---

## Task 1: worker 依赖 + 配置

**Files:**
- Modify: `services/worker/pyproject.toml`
- Create: `services/worker/src/agent_cloud_worker/config.py`
- Test: `services/worker/tests/test_config.py`

- [ ] **Step 1: 加依赖**

把 `services/worker/pyproject.toml` 的 `dependencies` 改为:

```toml
dependencies = [
    "agent-cloud-common",
    "grpcio",
    "openai",
    "pydantic-settings",
]
```

- [ ] **Step 2: 同步锁文件**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && uv lock
```
Expected: `uv.lock` 含 openai / pydantic-settings。

- [ ] **Step 3: 写失败测试**

Create `services/worker/tests/test_config.py`:

```python
from agent_cloud_worker.config import WorkerSettings


def test_defaults():
    s = WorkerSettings()
    assert s.grpc_port == 50052
    assert s.openai_base_url == "https://api.openai.com/v1"
    assert s.openai_max_retries == 2
    assert s.request_max_tokens == 4096


def test_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_WORKER_OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_CLOUD_WORKER_OPENAI_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("AGENT_CLOUD_WORKER_GRPC_PORT", "60000")
    s = WorkerSettings()
    assert s.openai_api_key == "sk-test"
    assert s.openai_base_url == "http://localhost:8000/v1"
    assert s.grpc_port == 60000
```

- [ ] **Step 4: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_config.py -q --timeout=60
```
Expected: FAIL（模块不存在）。

- [ ] **Step 5: 写 config**

Create `services/worker/src/agent_cloud_worker/config.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_CLOUD_WORKER_", env_file=".env")

    grpc_host: str = "0.0.0.0"
    grpc_port: int = 50052

    # OpenAI 兼容端点凭据(v1:单组,所有 agent 共用;每 key_ref 选择 + KMS 留后续)
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout_seconds: float = 60.0
    openai_max_retries: int = 2

    request_max_tokens: int = 4096


def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
```

- [ ] **Step 6: 跑测试确认通过 + commit**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_config.py -q --timeout=60
```
Expected: 2 passed。

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/worker/pyproject.toml uv.lock services/worker/src/agent_cloud_worker/config.py services/worker/tests/test_config.py && git commit -m "feat(worker): openai + pydantic-settings deps and WorkerSettings"
```

---

## Task 2: 领域 ↔ OpenAI 映射

**Files:**
- Create: `services/worker/src/agent_cloud_worker/openai_provider.py`(本任务先放映射函数)
- Test: `services/worker/tests/test_openai_mapping.py`

- [ ] **Step 1: 写失败测试**

Create `services/worker/tests/test_openai_mapping.py`:

```python
from types import SimpleNamespace

from agent_cloud_common import (
    CompletionRequest,
    Message,
    Role,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from agent_cloud_worker.openai_provider import (
    message_from_openai,
    to_openai_messages,
    to_openai_tools,
)


def test_to_openai_messages_includes_system_only_if_present():
    req = CompletionRequest(system="SYS", messages=[Message(role=Role.USER, text="hi")], tools=[])
    out = to_openai_messages(req)
    assert out[0] == {"role": "system", "content": "SYS"}
    assert out[1] == {"role": "user", "content": "hi"}

    req2 = CompletionRequest(system="", messages=[Message(role=Role.USER, text="hi")], tools=[])
    assert to_openai_messages(req2)[0] == {"role": "user", "content": "hi"}


def test_to_openai_messages_assistant_tool_calls_and_tool_results():
    msgs = [
        Message(
            role=Role.ASSISTANT,
            text="",
            tool_calls=[ToolCall(id="c1", name="bash", arguments={"command": "ls"})],
        ),
        Message(
            role=Role.TOOL,
            tool_results=[
                ToolResult(call_id="c1", content="file.txt", is_error=False),
            ],
        ),
    ]
    out = to_openai_messages(CompletionRequest(system="", messages=msgs, tools=[]))
    assert out[0]["role"] == "assistant"
    assert out[0]["tool_calls"][0]["id"] == "c1"
    assert out[0]["tool_calls"][0]["type"] == "function"
    assert out[0]["tool_calls"][0]["function"]["name"] == "bash"
    assert out[0]["tool_calls"][0]["function"]["arguments"] == '{"command": "ls"}'
    # tool 角色的每个 result 展开成一条 openai tool 消息
    assert out[1] == {"role": "tool", "tool_call_id": "c1", "content": "file.txt"}


def test_to_openai_tools():
    specs = [ToolSpec(name="bash", description="run", input_schema={"type": "object"})]
    out = to_openai_tools(specs)
    assert out == [
        {
            "type": "function",
            "function": {"name": "bash", "description": "run", "parameters": {"type": "object"}},
        }
    ]


def test_message_from_openai_text_only():
    om = SimpleNamespace(content="hello", tool_calls=None)
    m = message_from_openai(om)
    assert m.role == Role.ASSISTANT and m.text == "hello" and m.tool_calls == []


def test_message_from_openai_with_tool_calls_parses_json_arguments():
    om = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id="c1",
                function=SimpleNamespace(name="bash", arguments='{"command": "ls"}'),
            )
        ],
    )
    m = message_from_openai(om)
    assert m.text == ""
    assert m.tool_calls == [ToolCall(id="c1", name="bash", arguments={"command": "ls"})]
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_openai_mapping.py -q --timeout=60
```
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 写映射(放进新文件 openai_provider.py 顶部)**

Create `services/worker/src/agent_cloud_worker/openai_provider.py`:

```python
from __future__ import annotations

import json

from agent_cloud_common import (
    CompletionRequest,
    Message,
    Role,
    ToolCall,
    ToolSpec,
)


def to_openai_tools(tools: list[ToolSpec]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


def to_openai_messages(request: CompletionRequest) -> list[dict]:
    """领域消息 → OpenAI chat messages。tool 角色的每个 result 展开成一条 openai tool 消息。"""
    out: list[dict] = []
    if request.system:
        out.append({"role": "system", "content": request.system})
    for m in request.messages:
        if m.role == Role.USER:
            out.append({"role": "user", "content": m.text})
        elif m.role == Role.ASSISTANT:
            msg: dict = {"role": "assistant", "content": m.text or None}
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in m.tool_calls
                ]
            out.append(msg)
        elif m.role == Role.TOOL:
            for tr in m.tool_results:
                out.append({"role": "tool", "tool_call_id": tr.call_id, "content": tr.content})
    return out


def message_from_openai(om) -> Message:
    """OpenAI 响应 message → 领域 Message(assistant)。tool_call 参数始终 json.loads。"""
    tool_calls = [
        ToolCall(id=tc.id, name=tc.function.name, arguments=json.loads(tc.function.arguments or "{}"))
        for tc in (om.tool_calls or [])
    ]
    return Message(role=Role.ASSISTANT, text=om.content or "", tool_calls=tool_calls)
```

- [ ] **Step 4: 跑测试确认通过 + commit**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_openai_mapping.py -q --timeout=60
```
Expected: 全 passed。

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/worker/src/agent_cloud_worker/openai_provider.py services/worker/tests/test_openai_mapping.py && git commit -m "feat(worker): domain<->OpenAI chat message/tool mapping"
```

---

## Task 3: OpenAIProvider.complete(一元)

**Files:**
- Modify: `services/worker/src/agent_cloud_worker/openai_provider.py`(加类 + complete)
- Test: `services/worker/tests/test_openai_provider.py`

- [ ] **Step 1: 写失败测试**

Create `services/worker/tests/test_openai_provider.py`:

```python
from types import SimpleNamespace

from agent_cloud_common import CompletionRequest, Message, Role, ToolSpec
from agent_cloud_worker.openai_provider import OpenAIProvider


class _FakeCompletions:
    def __init__(self, response=None, captured=None):
        self._response = response
        self._captured = captured if captured is not None else {}

    async def create(self, **kwargs):
        self._captured.update(kwargs)
        return self._response


def _client(response, captured=None):
    return SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions(response, captured)))


def _req(system="SYS", text="hi", tools=None):
    return CompletionRequest(
        system=system, messages=[Message(role=Role.USER, text=text)], tools=tools or []
    )


async def test_complete_text_only():
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello", tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3),
    )
    provider = OpenAIProvider(client=_client(resp), model="m", max_tokens=99)
    result = await provider.complete(_req())
    assert result.message.role == Role.ASSISTANT
    assert result.message.text == "hello"
    assert result.usage.input_tokens == 5 and result.usage.output_tokens == 3


async def test_complete_with_tool_call():
    resp = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="c1",
                            function=SimpleNamespace(name="bash", arguments='{"command": "ls"}'),
                        )
                    ],
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )
    provider = OpenAIProvider(client=_client(resp), model="m", max_tokens=99)
    result = await provider.complete(_req())
    assert result.message.tool_calls[0].name == "bash"
    assert result.message.tool_calls[0].arguments == {"command": "ls"}


async def test_complete_passes_model_tools_and_max_tokens():
    captured = {}
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="x", tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0),
    )
    provider = OpenAIProvider(client=_client(resp, captured), model="gpt-x", max_tokens=123)
    await provider.complete(_req(tools=[ToolSpec(name="bash", description="d", input_schema={})]))
    assert captured["model"] == "gpt-x"
    assert captured["max_tokens"] == 123
    assert captured["tools"][0]["function"]["name"] == "bash"
    assert "stream" not in captured or captured["stream"] is False


async def test_complete_omits_tools_when_empty():
    captured = {}
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="x", tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0),
    )
    provider = OpenAIProvider(client=_client(resp, captured), model="m", max_tokens=1)
    await provider.complete(_req(tools=[]))
    assert "tools" not in captured  # 空工具集不传 tools 键
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_openai_provider.py -q --timeout=60
```
Expected: FAIL（`OpenAIProvider` 不存在）。

- [ ] **Step 3: 写 OpenAIProvider.complete**

在 `openai_provider.py` 顶部 import 区补上:
```python
from agent_cloud_common import CompletionResult, Usage
```
并在文件末尾追加:

```python
class OpenAIProvider:
    """OpenAI 兼容 chat completions 的 provider(注入 AsyncOpenAI 或兼容 client)。

    实现既有 Provider/StreamingProvider 协议(complete + stream)。client 由 factory
    用 base_url 覆盖构造,因此可对接任意 OpenAI 兼容端点。
    """

    def __init__(self, client, model: str, max_tokens: int) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    def _create_kwargs(self, request: CompletionRequest) -> dict:
        kwargs: dict = {
            "model": self._model,
            "messages": to_openai_messages(request),
            "max_tokens": self._max_tokens,
        }
        if request.tools:
            kwargs["tools"] = to_openai_tools(request.tools)
        return kwargs

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        resp = await self._client.chat.completions.create(**self._create_kwargs(request))
        message = message_from_openai(resp.choices[0].message)
        usage = Usage(
            input_tokens=resp.usage.prompt_tokens,
            output_tokens=resp.usage.completion_tokens,
        )
        return CompletionResult(message=message, usage=usage)
```

- [ ] **Step 4: 跑测试确认通过 + commit**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_openai_provider.py -q --timeout=60
```
Expected: 4 passed。

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/worker/src/agent_cloud_worker/openai_provider.py services/worker/tests/test_openai_provider.py && git commit -m "feat(worker): OpenAIProvider.complete (unary chat completions)"
```

---

## Task 4: OpenAIProvider.stream(流式)

**Files:**
- Modify: `services/worker/src/agent_cloud_worker/openai_provider.py`(加 stream)
- Test: `services/worker/tests/test_openai_provider.py`(追加流式用例)

- [ ] **Step 1: 追加失败测试**

在 `tests/test_openai_provider.py` 末尾追加:

```python
from agent_cloud_worker.provider import (  # noqa: E402
    ProviderCompleted,
    ProviderTextDelta,
    ProviderThinkingDelta,
)


def _stream_client(chunks, captured=None):
    cap = captured if captured is not None else {}

    class _Comp:
        async def create(self, **kwargs):
            cap.update(kwargs)

            async def _gen():
                for c in chunks:
                    yield c

            return _gen()

    return SimpleNamespace(chat=SimpleNamespace(completions=_Comp()))


def _delta(content=None, tool_calls=None, reasoning=None):
    d = SimpleNamespace(content=content, tool_calls=tool_calls, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(delta=d, finish_reason=None)], usage=None)


def _usage_chunk(pt, ct):
    return SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct))


async def test_stream_text_then_completed():
    chunks = [_delta(content="he"), _delta(content="llo"), _usage_chunk(5, 2)]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    texts = [e.text for e in events if isinstance(e, ProviderTextDelta)]
    assert texts == ["he", "llo"]
    done = events[-1]
    assert isinstance(done, ProviderCompleted)
    assert done.message.text == "hello"
    assert done.usage.input_tokens == 5 and done.usage.output_tokens == 2


async def test_stream_accumulates_tool_call_arguments():
    tc0 = SimpleNamespace(index=0, id="c1", function=SimpleNamespace(name="bash", arguments='{"comm'))
    tc1 = SimpleNamespace(index=0, id=None, function=SimpleNamespace(name=None, arguments='and": "ls"}'))
    chunks = [
        _delta(tool_calls=[tc0]),
        _delta(tool_calls=[tc1]),
        _usage_chunk(1, 1),
    ]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    done = events[-1]
    assert isinstance(done, ProviderCompleted)
    assert done.message.tool_calls[0].name == "bash"
    assert done.message.tool_calls[0].arguments == {"command": "ls"}


async def test_stream_maps_reasoning_content_to_thinking():
    chunks = [_delta(reasoning="thinking..."), _delta(content="answer"), _usage_chunk(1, 1)]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    assert any(isinstance(e, ProviderThinkingDelta) and e.text == "thinking..." for e in events)
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_openai_provider.py -q --timeout=60
```
Expected: 流式用例 FAIL（无 stream）。

- [ ] **Step 3: 写 stream**

在 `openai_provider.py` 顶部 import 区补上:
```python
from collections.abc import AsyncIterator

from agent_cloud_worker.provider import (
    ProviderCompleted,
    ProviderEvent,
    ProviderTextDelta,
    ProviderThinkingDelta,
)
```
并在 `OpenAIProvider` 类内追加方法:

```python
    async def stream(self, request: CompletionRequest) -> AsyncIterator[ProviderEvent]:
        kwargs = self._create_kwargs(request)
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}
        stream = await self._client.chat.completions.create(**kwargs)

        text_parts: list[str] = []
        # index -> {"id","name","args"};按 index 累积分片的 tool_call 参数
        tool_acc: dict[int, dict] = {}
        usage = Usage()

        async for chunk in stream:
            if chunk.usage is not None:
                usage = Usage(
                    input_tokens=chunk.usage.prompt_tokens,
                    output_tokens=chunk.usage.completion_tokens,
                )
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield ProviderThinkingDelta(text=reasoning)
            if delta.content:
                text_parts.append(delta.content)
                yield ProviderTextDelta(text=delta.content)
            for tcd in delta.tool_calls or []:
                slot = tool_acc.setdefault(tcd.index, {"id": "", "name": "", "args": ""})
                if tcd.id:
                    slot["id"] = tcd.id
                if tcd.function and tcd.function.name:
                    slot["name"] = tcd.function.name
                if tcd.function and tcd.function.arguments:
                    slot["args"] += tcd.function.arguments

        tool_calls = [
            ToolCall(id=s["id"], name=s["name"], arguments=json.loads(s["args"] or "{}"))
            for _, s in sorted(tool_acc.items())
        ]
        message = Message(role=Role.ASSISTANT, text="".join(text_parts), tool_calls=tool_calls)
        yield ProviderCompleted(message=message, usage=usage)
```

- [ ] **Step 4: 跑测试确认通过 + commit**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_openai_provider.py -q --timeout=60
```
Expected: 全 passed(一元 + 流式)。

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/worker/src/agent_cloud_worker/openai_provider.py services/worker/tests/test_openai_provider.py && git commit -m "feat(worker): OpenAIProvider.stream (deltas + tool-call accumulation + usage)"
```

---

## Task 5: 凭据解析 + provider factory

**Files:**
- Create: `services/worker/src/agent_cloud_worker/factory.py`
- Test: `services/worker/tests/test_factory.py`

- [ ] **Step 1: 写失败测试**

Create `services/worker/tests/test_factory.py`:

```python
import pytest

from agent_cloud_worker.config import WorkerSettings
from agent_cloud_worker.factory import build_provider_factory
from agent_cloud_worker.openai_provider import OpenAIProvider


def test_factory_builds_openai_provider():
    settings = WorkerSettings(openai_api_key="sk-x", openai_base_url="http://ep/v1")
    factory = build_provider_factory(settings)
    provider = factory("gpt-x", "openai", "ref-1")
    assert isinstance(provider, OpenAIProvider)
    assert provider._model == "gpt-x"
    # client 用配置的 base_url(AsyncOpenAI 暴露 .base_url)
    assert str(provider._client.base_url).rstrip("/").endswith("/v1")


def test_factory_missing_api_key_raises():
    factory = build_provider_factory(WorkerSettings(openai_api_key=""))
    with pytest.raises(RuntimeError, match="API key"):
        factory("m", "openai", "ref")
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_factory.py -q --timeout=60
```
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 写 factory**

Create `services/worker/src/agent_cloud_worker/factory.py`:

```python
from __future__ import annotations

from openai import AsyncOpenAI

from agent_cloud_worker.config import WorkerSettings
from agent_cloud_worker.openai_provider import OpenAIProvider
from agent_cloud_worker.provider import Provider
from agent_cloud_worker.server import ProviderFactory


def build_provider_factory(settings: WorkerSettings) -> ProviderFactory:
    """造一个 provider_factory(model, provider, key_ref)->Provider。

    v1:所有 key_ref 共用 settings 里配置的单组 {api_key, base_url}(每 key_ref 选择 +
    KMS 留后续)。openai SDK 自带 timeout + max_retries(自动退避 429/5xx)。
    """

    def factory(model: str, provider: str, key_ref: str) -> Provider:
        if not settings.openai_api_key:
            raise RuntimeError(
                "OpenAI API key not configured (set AGENT_CLOUD_WORKER_OPENAI_API_KEY)"
            )
        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )
        return OpenAIProvider(client=client, model=model, max_tokens=settings.request_max_tokens)

    return factory
```

- [ ] **Step 4: 跑测试确认通过 + commit**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_factory.py -q --timeout=60
```
Expected: 2 passed。

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/worker/src/agent_cloud_worker/factory.py services/worker/tests/test_factory.py && git commit -m "feat(worker): env/config-driven OpenAI provider factory"
```

---

## Task 6: worker 入口 + 一元 RunTurn 错误映射(韧性)

**Files:**
- Create: `services/worker/src/agent_cloud_worker/__main__.py`
- Modify: `services/worker/src/agent_cloud_worker/server.py`
- Test: `services/worker/tests/test_server_provider_error.py`

- [ ] **Step 1: 写失败测试(provider 失败 → 干净 gRPC INTERNAL)**

Create `services/worker/tests/test_server_provider_error.py`:

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_server_provider_error.py -q --timeout=60
```
Expected: FAIL（当前一元 RunTurn 未捕获 provider 异常 → 冒泡成 UNKNOWN,而非 INTERNAL)。

- [ ] **Step 3: 一元 RunTurn 包错误映射**

在 `server.py` 的 `RunTurn` 里,把现有的:
```python
        async with grpc.aio.insecure_channel(
            request.sandbox_endpoint,
            options=[
                ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
                ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
            ],
        ) as channel:
            executor = SandboxToolExecutor(
                channel, request.work_subdir, list(request.agent.enabled_tools)
            )
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
```
改为(把 run_turn 包进 try/except,provider/loop 失败收敛为 INTERNAL,与流式路径一致;不泄漏原始异常文本):
```python
        async with grpc.aio.insecure_channel(
            request.sandbox_endpoint,
            options=[
                ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
                ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
            ],
        ) as channel:
            executor = SandboxToolExecutor(
                channel, request.work_subdir, list(request.agent.enabled_tools)
            )
            try:
                result = await run_turn(
                    provider,
                    executor,
                    system=system,
                    history=history,
                    user_message=request.user_message,
                )
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
        )
```

- [ ] **Step 4: 写 worker 入口**

Create `services/worker/src/agent_cloud_worker/__main__.py`:

```python
from __future__ import annotations

import asyncio
import logging

from agent_cloud_worker.config import get_worker_settings
from agent_cloud_worker.factory import build_provider_factory
from agent_cloud_worker.server import create_server

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_worker_settings()
    factory = build_provider_factory(settings)
    server, port = await create_server(
        provider_factory=factory, host=settings.grpc_host, port=settings.grpc_port
    )
    logger.info("agent-cloud worker listening on %s:%s", settings.grpc_host, port)
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 5: 跑测试确认通过 + 入口冒烟**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_server_provider_error.py -q --timeout=60
```
Expected: 1 passed。

入口冒烟(import 不炸):
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run python -c "import agent_cloud_worker.__main__ as m; import inspect; assert inspect.iscoroutinefunction(m.main); print('entrypoint ok')"
```
Expected: 打印 `entrypoint ok`。

- [ ] **Step 6: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/worker/src/agent_cloud_worker/__main__.py services/worker/src/agent_cloud_worker/server.py services/worker/tests/test_server_provider_error.py && git commit -m "feat(worker): production entrypoint + map unary provider failure to INTERNAL"
```

---

## Task 7: 收尾(全量回归 + lint)

**Files:** 无(仅验证)

- [ ] **Step 1: worker 全量**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest -q --timeout=60
```
Expected: 全绿(原 54 + 本计划新增约 15)。

- [ ] **Step 2: 其余套件回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/packages/common && uv run pytest -q --timeout=60
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run pytest -q --timeout=60
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q --timeout=120
```
Expected: 全绿(backend 一次进程跑完——teardown 挂死已修)。

- [ ] **Step 3: ruff**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && uv run ruff check services/worker
```
Expected: `All checks passed!`(如有 import 排序/行长问题:`--fix` 后复跑;注意 E501 不自动修)。

- [ ] **Step 4: 最终 commit(若 ruff 有改动)**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add -A services/worker && git commit -m "chore(worker): ruff clean for OpenAI provider"
```

---

## Self-Review(对照 spec §5/§6/§10 + 用户的 OpenAI 决策)

- **真实 LLM provider(OpenAI 接口格式)**:Task 2–4 `OpenAIProvider`(complete + stream)走 OpenAI 兼容 chat completions;官方 `openai` SDK + `base_url` 覆盖 → 任意兼容端点。✔
- **替换 FakeProvider 走通回合**:Task 5 factory + Task 6 入口把真实 provider 接进既有 worker server / run_turn loop(server 早已用 request.skills / enabled_tools)。✔
- **凭据(spec §5.1 ProviderKeys 只在 worker)**:Task 1/5 env/config 解析,key 只在 worker(不下沉沙箱)。v1 单组凭据;每 key_ref 选择 + KMS 留后续。✔(已在计划标注偏差)
- **韧性(spec §10)**:Task 5 openai SDK timeout + max_retries(自动退避 429/5xx);Task 6 一元 RunTurn provider 失败 → INTERNAL(与流式一致)→ 后端 502,回合失败无半成品。✔
- **工具调用**:复用 worker 既有 run_turn loop + sandbox 执行;provider 只做 OpenAI 工具格式 ↔ 领域 ToolCall/ToolResult 映射;参数始终 `json.loads`。✔
- **流式**:Task 4 文本/思考增量 + 按 index 累积 tool_call 参数 + include_usage 取用量;worker run_turn_stream 已消费这些 ProviderEvent。✔
- **留作后续**:每 key_ref 凭据选择 + KMS 加密;后端回合级重试(换 worker);thinking 仅在端点给 `reasoning_content` 时透传。

类型/签名一致性:`to_openai_messages(request)`、`to_openai_tools(tools)`、`message_from_openai(om)`、`OpenAIProvider(client, model, max_tokens)` 实现 `complete`/`stream`、`build_provider_factory(settings)->ProviderFactory`、`WorkerSettings`、`__main__.main`、`ProviderEvent`(ProviderTextDelta/ThinkingDelta/Completed)—— 跨任务与既有 `provider.py`/`server.py` 协议一致。✔
