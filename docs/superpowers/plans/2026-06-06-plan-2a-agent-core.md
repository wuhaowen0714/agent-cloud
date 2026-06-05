# Plan 2a: Agent 核心库(worker) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 agent 的"脑"——回合循环(agent-loop)、provider 抽象、工具接口与本地工具执行器,用假 LLM provider 驱动,纯库、可独立测试,不涉网络/沙箱/gRPC。

**Architecture:** 新建 workspace 成员 `services/worker`(包 `agent_cloud_worker`)。共享领域类型放进 `packages/common`(包 `agent_cloud_common`)。worker 依赖 common。核心是 `run_turn()`:给定 system + 历史 + 新用户消息 + 一个 `Provider` 和一个 `ToolExecutor`,循环"调 LLM → 若有工具调用则执行并回填 → 直到无工具调用或达上限"。Provider 与 ToolExecutor 都是 Protocol;本计划提供 `FakeProvider`(脚本化)与 `LocalToolExecutor`(在临时工作目录跑 bash/读写文件)。

**Tech Stack:** Python 3.12+、uv workspace、纯 stdlib(dataclasses/enum/asyncio/subprocess)、pytest + pytest-asyncio + ruff。**无 DB、无 Docker**——全部是快速单元测试。

参考:设计 spec `docs/superpowers/specs/2026-06-05-stateless-agent-cloud-design.md`(§4.2 worker 职责、§5.3 上下文组装、§7 契约、§8 回合循环、§12 测试)。openclaw 的 `packages/agent-core/src/agent-loop.ts` 是结构蓝本(非端口)。

---

## 范围

**做**:`agent_cloud_common` 领域类型;worker 的 provider 抽象 + FakeProvider;工具接口 + LocalToolExecutor + 内置工具(bash/write_file/read_file);上下文组装 `build_system_prompt`;`run_turn` 回合循环。全部纯内存 + 临时目录测试。

**不做(后续 Plan 2b+)**:gRPC/protos、worker 服务器、真实沙箱、后端编排、真实 LLM provider、流式、会话锁。本计划的 `Provider`/`ToolExecutor` 接口正是 2b 接 gRPC/真沙箱/真 provider 的接缝。

`agent_cloud_common` 领域类型为纯 dataclass(无第三方依赖);它们由 worker 的测试充分覆盖(消费者驱动),不单独建 common 测试套件。

## File Structure

```
packages/common/src/agent_cloud_common/
  __init__.py            # 导出领域类型
  types.py               # Role, Message, ToolCall, ToolResult, ToolSpec, Usage,
                         #   CompletionRequest, CompletionResult,
                         #   ContextDocument, MemoryItem, SkillRef
services/worker/
  pyproject.toml         # agent-cloud-worker(依赖 agent-cloud-common;dev: pytest/...)
  src/agent_cloud_worker/
    __init__.py          # 导出公共 API(run_turn 等)
    provider.py          # Provider Protocol + FakeProvider
    tools.py             # Tool, ToolExecutor Protocol, LocalToolExecutor, builtin_tools()
    context.py           # build_system_prompt(...)
    loop.py              # TurnResult, run_turn(...)
  tests/
    __init__.py
    test_provider.py
    test_tools.py
    test_context.py
    test_loop.py
```

每文件单一职责:`types` 纯数据;`provider` 只管"如何得到下一条 assistant 消息";`tools` 只管"如何执行一次工具调用";`context` 只管"把文档/记忆/技能拼成 system 文本";`loop` 只编排这几者。

---

### Task 0: 新建 worker 包并纳入 workspace

**Files:**
- Create: `services/worker/pyproject.toml`, `services/worker/src/agent_cloud_worker/__init__.py`, `services/worker/tests/__init__.py`

- [ ] **Step 1: 写 worker 包的 pyproject**

Create `services/worker/pyproject.toml`:
```toml
[project]
name = "agent-cloud-worker"
version = "0.0.0"
requires-python = ">=3.12"
dependencies = [
    "agent-cloud-common",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agent_cloud_worker"]

[tool.uv.sources]
agent-cloud-common = { workspace = true }

[dependency-groups]
dev = [
    "pytest",
    "pytest-asyncio",
    "ruff",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
pythonpath = ["src"]
```

Create empty `services/worker/src/agent_cloud_worker/__init__.py` and `services/worker/tests/__init__.py`.

- [ ] **Step 2: 同步 workspace(自动识别新成员)**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && uv sync
```
Expected: `agent-cloud-worker` 作为新 workspace 成员被解析安装(root `pyproject.toml` 的 `members = ["packages/*", "services/*"]` 已涵盖)。

- [ ] **Step 3: 提交**

```bash
git add services/worker/pyproject.toml services/worker/src/agent_cloud_worker/__init__.py services/worker/tests/__init__.py uv.lock
git commit -m "chore(worker): scaffold agent-cloud-worker package in workspace"
```

---

### Task 1: 共享领域类型(agent_cloud_common)

**Files:**
- Create: `packages/common/src/agent_cloud_common/types.py`
- Modify: `packages/common/src/agent_cloud_common/__init__.py`

> 纯数据类,无依赖;由 worker 测试覆盖。

- [ ] **Step 1: 写 types.py**

Create `packages/common/src/agent_cloud_common/types.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    role: Role
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)   # assistant 用
    tool_results: list[ToolResult] = field(default_factory=list)  # tool 角色用


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class CompletionRequest:
    system: str
    messages: list[Message]
    tools: list[ToolSpec]


@dataclass
class CompletionResult:
    message: Message
    usage: Usage


# ---- 上下文组装的输入(后端会在 2b 通过 run_turn 传入)----
@dataclass
class ContextDocument:
    scope: str  # "user" | "agent"
    type: str   # "USER" | "AGENTS" | ...
    content: str


@dataclass
class MemoryItem:
    scope: str  # "user" | "agent"
    content: str


@dataclass
class SkillRef:
    name: str
    description: str
    location: str
```

- [ ] **Step 2: 导出**

Replace `packages/common/src/agent_cloud_common/__init__.py`:
```python
from agent_cloud_common.types import (
    CompletionRequest,
    CompletionResult,
    ContextDocument,
    MemoryItem,
    Message,
    Role,
    SkillRef,
    ToolCall,
    ToolResult,
    ToolSpec,
    Usage,
)

__all__ = [
    "Role",
    "Message",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "Usage",
    "CompletionRequest",
    "CompletionResult",
    "ContextDocument",
    "MemoryItem",
    "SkillRef",
]
```

- [ ] **Step 3: 冒烟导入(确认包可导入)**

Run: `cd services/worker && uv run python -c "from agent_cloud_common import Message, Role; print(Message(role=Role.USER, text='hi'))"`
Expected: 打印一个 `Message(...)`,无导入错误。

- [ ] **Step 4: 提交**

```bash
git add packages/common/src/agent_cloud_common/types.py packages/common/src/agent_cloud_common/__init__.py
git commit -m "feat(common): add shared agent domain types"
```

---

### Task 2: Provider 抽象 + FakeProvider

**Files:**
- Create: `services/worker/src/agent_cloud_worker/provider.py`
- Test: `services/worker/tests/test_provider.py`

- [ ] **Step 1: 写失败测试**

Create `services/worker/tests/test_provider.py`:
```python
import pytest

from agent_cloud_common import (
    CompletionRequest,
    CompletionResult,
    Message,
    Role,
    Usage,
)
from agent_cloud_worker.provider import FakeProvider


def _result(text: str) -> CompletionResult:
    return CompletionResult(
        message=Message(role=Role.ASSISTANT, text=text),
        usage=Usage(input_tokens=1, output_tokens=1),
    )


async def test_fake_provider_returns_scripted_in_order():
    provider = FakeProvider([_result("a"), _result("b")])
    req = CompletionRequest(system="", messages=[], tools=[])
    r1 = await provider.complete(req)
    r2 = await provider.complete(req)
    assert r1.message.text == "a"
    assert r2.message.text == "b"


async def test_fake_provider_raises_when_exhausted():
    provider = FakeProvider([_result("only")])
    req = CompletionRequest(system="", messages=[], tools=[])
    await provider.complete(req)
    with pytest.raises(IndexError):
        await provider.complete(req)
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd services/worker && uv run pytest tests/test_provider.py -v`
Expected: FAIL(`ModuleNotFoundError: agent_cloud_worker.provider`)。

- [ ] **Step 3: 写 provider.py**

Create `services/worker/src/agent_cloud_worker/provider.py`:
```python
from __future__ import annotations

from typing import Protocol

from agent_cloud_common import CompletionRequest, CompletionResult


class Provider(Protocol):
    async def complete(self, request: CompletionRequest) -> CompletionResult: ...


class FakeProvider:
    """脚本化 provider:按顺序返回预设的 CompletionResult。用于确定性测试 agent-loop。"""

    def __init__(self, scripted: list[CompletionResult]) -> None:
        self._scripted = list(scripted)
        self._index = 0

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        result = self._scripted[self._index]  # 耗尽时抛 IndexError
        self._index += 1
        return result
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd services/worker && uv run pytest tests/test_provider.py -v`
Expected: PASS(2 passed)。

- [ ] **Step 5: 提交**

```bash
git add services/worker/src/agent_cloud_worker/provider.py services/worker/tests/test_provider.py
git commit -m "feat(worker): add Provider protocol and FakeProvider"
```

---

### Task 3: 工具接口 + LocalToolExecutor + 内置工具

**Files:**
- Create: `services/worker/src/agent_cloud_worker/tools.py`
- Test: `services/worker/tests/test_tools.py`

- [ ] **Step 1: 写失败测试**

Create `services/worker/tests/test_tools.py`:
```python
from agent_cloud_common import ToolCall
from agent_cloud_worker.tools import LocalToolExecutor, builtin_tools


def _executor(tmp_path):
    return LocalToolExecutor(workdir=tmp_path, tools=builtin_tools())


def test_specs_lists_builtin_tools(tmp_path):
    names = {s.name for s in _executor(tmp_path).specs()}
    assert {"bash", "write_file", "read_file"} <= names


async def test_write_then_read(tmp_path):
    ex = _executor(tmp_path)
    w = await ex.execute(ToolCall(id="1", name="write_file",
                                  arguments={"path": "a.txt", "content": "hello"}))
    assert w.is_error is False
    r = await ex.execute(ToolCall(id="2", name="read_file", arguments={"path": "a.txt"}))
    assert r.is_error is False
    assert r.content == "hello"
    assert (tmp_path / "a.txt").read_text() == "hello"


async def test_bash_runs_in_workdir(tmp_path):
    ex = _executor(tmp_path)
    r = await ex.execute(ToolCall(id="1", name="bash", arguments={"command": "echo hi"}))
    assert r.is_error is False
    assert "hi" in r.content


async def test_bash_nonzero_exit_is_error(tmp_path):
    ex = _executor(tmp_path)
    r = await ex.execute(ToolCall(id="1", name="bash", arguments={"command": "exit 3"}))
    assert r.is_error is True


async def test_unknown_tool_returns_error(tmp_path):
    ex = _executor(tmp_path)
    r = await ex.execute(ToolCall(id="1", name="nope", arguments={}))
    assert r.is_error is True
    assert "unknown tool" in r.content.lower()
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd services/worker && uv run pytest tests/test_tools.py -v`
Expected: FAIL(`ModuleNotFoundError: agent_cloud_worker.tools`)。

- [ ] **Step 3: 写 tools.py**

Create `services/worker/src/agent_cloud_worker/tools.py`:
```python
from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agent_cloud_common import ToolCall, ToolResult, ToolSpec


@dataclass
class Tool:
    spec: ToolSpec
    func: Callable[[Path, dict], str]  # 同步实现;executor 在线程里跑


class ToolExecutor(Protocol):
    def specs(self) -> list[ToolSpec]: ...
    async def execute(self, call: ToolCall) -> ToolResult: ...


class LocalToolExecutor:
    """在本地临时工作目录执行工具。是未来 gRPC 沙箱执行器的本地替身(同一接口)。"""

    def __init__(self, workdir: Path, tools: list[Tool]) -> None:
        self.workdir = Path(workdir)
        self._tools = {t.spec.name: t for t in tools}

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    async def execute(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(call_id=call.id, content=f"unknown tool: {call.name}", is_error=True)
        try:
            content = await asyncio.to_thread(tool.func, self.workdir, call.arguments)
            return ToolResult(call_id=call.id, content=content, is_error=False)
        except Exception as exc:  # 工具失败回填为错误结果,交回模型决定下一步
            return ToolResult(call_id=call.id, content=str(exc), is_error=True)


# ---- 内置工具实现 ----
def _bash(workdir: Path, args: dict) -> str:
    proc = subprocess.run(
        args["command"], shell=True, cwd=workdir,
        capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr
    if proc.returncode != 0:
        raise RuntimeError(f"exit {proc.returncode}: {output}")
    return output


def _write_file(workdir: Path, args: dict) -> str:
    target = workdir / args["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(args["content"])
    return f"wrote {args['path']}"


def _read_file(workdir: Path, args: dict) -> str:
    return (workdir / args["path"]).read_text()


def builtin_tools() -> list[Tool]:
    return [
        Tool(
            spec=ToolSpec(
                name="bash",
                description="Run a shell command in the working directory.",
                input_schema={"type": "object", "properties": {"command": {"type": "string"}},
                              "required": ["command"]},
            ),
            func=_bash,
        ),
        Tool(
            spec=ToolSpec(
                name="write_file",
                description="Write text to a file (relative to the working directory).",
                input_schema={"type": "object",
                              "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                              "required": ["path", "content"]},
            ),
            func=_write_file,
        ),
        Tool(
            spec=ToolSpec(
                name="read_file",
                description="Read a file (relative to the working directory).",
                input_schema={"type": "object", "properties": {"path": {"type": "string"}},
                              "required": ["path"]},
            ),
            func=_read_file,
        ),
    ]
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd services/worker && uv run pytest tests/test_tools.py -v`
Expected: PASS(5 passed)。

- [ ] **Step 5: 提交**

```bash
git add services/worker/src/agent_cloud_worker/tools.py services/worker/tests/test_tools.py
git commit -m "feat(worker): add tool interface, LocalToolExecutor, builtin tools"
```

---

### Task 4: 上下文组装(build_system_prompt)

**Files:**
- Create: `services/worker/src/agent_cloud_worker/context.py`
- Test: `services/worker/tests/test_context.py`

- [ ] **Step 1: 写失败测试**

Create `services/worker/tests/test_context.py`:
```python
from agent_cloud_common import ContextDocument, MemoryItem, SkillRef
from agent_cloud_worker.context import build_system_prompt


def test_layers_user_then_agent_docs():
    out = build_system_prompt(
        documents=[
            ContextDocument(scope="agent", type="AGENTS", content="AGENT BODY"),
            ContextDocument(scope="user", type="USER", content="USER BODY"),
        ],
        memory=[],
        skills=[],
    )
    assert "USER BODY" in out and "AGENT BODY" in out
    # 用户级文档排在 agent 级之前
    assert out.index("USER BODY") < out.index("AGENT BODY")


def test_includes_memory_and_skills():
    out = build_system_prompt(
        documents=[],
        memory=[MemoryItem(scope="user", content="likes tea")],
        skills=[SkillRef(name="weather", description="get weather", location="/skills/weather/SKILL.md")],
    )
    assert "likes tea" in out
    assert "weather" in out
    assert "/skills/weather/SKILL.md" in out
    assert "<available_skills>" in out


def test_empty_inputs_produce_empty_string():
    assert build_system_prompt(documents=[], memory=[], skills=[]) == ""
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd services/worker && uv run pytest tests/test_context.py -v`
Expected: FAIL(`ModuleNotFoundError: agent_cloud_worker.context`)。

- [ ] **Step 3: 写 context.py**

Create `services/worker/src/agent_cloud_worker/context.py`:
```python
from __future__ import annotations

from agent_cloud_common import ContextDocument, MemoryItem, SkillRef


def _render_docs(documents: list[ContextDocument]) -> list[str]:
    # 用户级在前,agent 级在后;各自保持输入顺序
    ordered = [d for d in documents if d.scope == "user"] + [
        d for d in documents if d.scope != "user"
    ]
    return [f"# {d.type} ({d.scope})\n{d.content}" for d in ordered]


def _render_memory(memory: list[MemoryItem]) -> list[str]:
    if not memory:
        return []
    lines = ["# Memory"]
    for m in memory:
        lines.append(f"- ({m.scope}) {m.content}")
    return ["\n".join(lines)]


def _render_skills(skills: list[SkillRef]) -> list[str]:
    if not skills:
        return []
    lines = [
        "The following skills provide specialized instructions for specific tasks.",
        "Read a skill's file (location) when the task matches its description.",
        "<available_skills>",
    ]
    for s in skills:
        lines.append(f"  <skill><name>{s.name}</name>"
                     f"<description>{s.description}</description>"
                     f"<location>{s.location}</location></skill>")
    lines.append("</available_skills>")
    return ["\n".join(lines)]


def build_system_prompt(
    *,
    documents: list[ContextDocument],
    memory: list[MemoryItem],
    skills: list[SkillRef],
) -> str:
    """把配置文档(用户级在前)、记忆、技能元数据拼成分层 system 文本(spec §5.3)。"""
    sections = _render_docs(documents) + _render_memory(memory) + _render_skills(skills)
    return "\n\n".join(sections)
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd services/worker && uv run pytest tests/test_context.py -v`
Expected: PASS(3 passed)。

- [ ] **Step 5: 提交**

```bash
git add services/worker/src/agent_cloud_worker/context.py services/worker/tests/test_context.py
git commit -m "feat(worker): add layered system-prompt assembly"
```

---

### Task 5: Agent 回合循环(run_turn)

**Files:**
- Create: `services/worker/src/agent_cloud_worker/loop.py`
- Test: `services/worker/tests/test_loop.py`

- [ ] **Step 1: 写失败测试(覆盖多种回合场景)**

Create `services/worker/tests/test_loop.py`:
```python
from agent_cloud_common import (
    CompletionResult,
    Message,
    Role,
    ToolCall,
    Usage,
)
from agent_cloud_worker.loop import run_turn
from agent_cloud_worker.provider import FakeProvider
from agent_cloud_worker.tools import LocalToolExecutor, builtin_tools


def _say(text: str) -> CompletionResult:
    return CompletionResult(
        message=Message(role=Role.ASSISTANT, text=text),
        usage=Usage(input_tokens=10, output_tokens=5),
    )


def _call(tool: str, args: dict, text: str = "") -> CompletionResult:
    return CompletionResult(
        message=Message(role=Role.ASSISTANT, text=text,
                        tool_calls=[ToolCall(id="c1", name=tool, arguments=args)]),
        usage=Usage(input_tokens=10, output_tokens=5),
    )


def _executor(tmp_path):
    return LocalToolExecutor(workdir=tmp_path, tools=builtin_tools())


async def test_single_response_no_tools(tmp_path):
    provider = FakeProvider([_say("final answer")])
    result = await run_turn(
        provider, _executor(tmp_path),
        system="", history=[], user_message="hi",
    )
    assert result.stop_reason == "end_turn"
    assert len(result.new_messages) == 1
    assert result.new_messages[0].role == Role.ASSISTANT
    assert result.new_messages[0].text == "final answer"
    # 不把用户消息算进 new_messages(后端单独持久化)
    assert all(m.role != Role.USER for m in result.new_messages)
    assert result.usage.output_tokens == 5


async def test_one_tool_round_then_finish(tmp_path):
    provider = FakeProvider([
        _call("write_file", {"path": "out.txt", "content": "data"}),
        _say("done"),
    ])
    result = await run_turn(
        provider, _executor(tmp_path),
        system="", history=[], user_message="write it",
    )
    assert result.stop_reason == "end_turn"
    # assistant(含 tool_call) -> tool 结果消息 -> assistant(final)
    assert [m.role for m in result.new_messages] == [Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]
    assert (tmp_path / "out.txt").read_text() == "data"
    tool_msg = result.new_messages[1]
    assert tool_msg.tool_results[0].is_error is False
    # 两次 provider 调用的 usage 累加
    assert result.usage.output_tokens == 10


async def test_tool_error_feeds_back_and_continues(tmp_path):
    provider = FakeProvider([
        _call("nope", {}),     # 未知工具 -> 错误结果回填
        _say("recovered"),
    ])
    result = await run_turn(
        provider, _executor(tmp_path),
        system="", history=[], user_message="go",
    )
    assert result.stop_reason == "end_turn"
    assert result.new_messages[1].tool_results[0].is_error is True
    assert result.new_messages[-1].text == "recovered"


async def test_max_iterations_guard(tmp_path):
    # provider 永远返回工具调用,永不停止
    provider = FakeProvider([_call("bash", {"command": "echo x"}) for _ in range(10)])
    result = await run_turn(
        provider, _executor(tmp_path),
        system="", history=[], user_message="loop",
        max_iterations=3,
    )
    assert result.stop_reason == "max_iterations"
    # 3 轮 = 3 个 assistant + 3 个 tool 消息
    assert len(result.new_messages) == 6


async def test_history_is_preserved_in_request(tmp_path):
    # provider 校验它收到的 messages 含历史 + 新用户消息
    seen = {}

    class RecordingProvider:
        async def complete(self, request):
            seen["messages"] = request.messages
            return _say("ok")

    history = [Message(role=Role.USER, text="earlier"),
               Message(role=Role.ASSISTANT, text="reply")]
    await run_turn(RecordingProvider(), _executor(tmp_path),
                   system="SYS", history=history, user_message="now")
    texts = [m.text for m in seen["messages"]]
    assert texts == ["earlier", "reply", "now"]
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd services/worker && uv run pytest tests/test_loop.py -v`
Expected: FAIL(`ModuleNotFoundError: agent_cloud_worker.loop`)。

- [ ] **Step 3: 写 loop.py**

Create `services/worker/src/agent_cloud_worker/loop.py`:
```python
from __future__ import annotations

from dataclasses import dataclass

from agent_cloud_common import (
    CompletionRequest,
    Message,
    Role,
    Usage,
)

from agent_cloud_worker.provider import Provider
from agent_cloud_worker.tools import ToolExecutor


@dataclass
class TurnResult:
    new_messages: list[Message]   # 本回合新增的 assistant/tool 消息(不含用户消息)
    usage: Usage
    stop_reason: str              # "end_turn" | "max_iterations"


async def run_turn(
    provider: Provider,
    executor: ToolExecutor,
    *,
    system: str,
    history: list[Message],
    user_message: str,
    max_iterations: int = 10,
) -> TurnResult:
    """跑一个回合:调 LLM → 有工具调用则执行并回填 → 直到无工具调用或达上限。

    用户消息由调用方(后端)单独持久化,因此不计入 new_messages。
    """
    working: list[Message] = [*history, Message(role=Role.USER, text=user_message)]
    new_messages: list[Message] = []
    usage = Usage()

    for _ in range(max_iterations):
        result = await provider.complete(
            CompletionRequest(system=system, messages=working, tools=executor.specs())
        )
        usage.input_tokens += result.usage.input_tokens
        usage.output_tokens += result.usage.output_tokens

        assistant = result.message
        working.append(assistant)
        new_messages.append(assistant)

        if not assistant.tool_calls:
            return TurnResult(new_messages=new_messages, usage=usage, stop_reason="end_turn")

        tool_results = [await executor.execute(call) for call in assistant.tool_calls]
        tool_message = Message(role=Role.TOOL, tool_results=tool_results)
        working.append(tool_message)
        new_messages.append(tool_message)

    return TurnResult(new_messages=new_messages, usage=usage, stop_reason="max_iterations")
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd services/worker && uv run pytest tests/test_loop.py -v`
Expected: PASS(5 passed)。

- [ ] **Step 5: 提交**

```bash
git add services/worker/src/agent_cloud_worker/loop.py services/worker/tests/test_loop.py
git commit -m "feat(worker): add agent run_turn loop"
```

---

### Task 6: 导出 + lint + README + 全回归

**Files:**
- Modify: `services/worker/src/agent_cloud_worker/__init__.py`
- Create: `services/worker/README.md`

- [ ] **Step 1: 导出公共 API**

Replace `services/worker/src/agent_cloud_worker/__init__.py`:
```python
from agent_cloud_worker.context import build_system_prompt
from agent_cloud_worker.loop import TurnResult, run_turn
from agent_cloud_worker.provider import FakeProvider, Provider
from agent_cloud_worker.tools import (
    LocalToolExecutor,
    Tool,
    ToolExecutor,
    builtin_tools,
)

__all__ = [
    "run_turn",
    "TurnResult",
    "Provider",
    "FakeProvider",
    "ToolExecutor",
    "LocalToolExecutor",
    "Tool",
    "builtin_tools",
    "build_system_prompt",
]
```

- [ ] **Step 2: lint**

Run: `cd services/worker && uv run ruff check . && uv run ruff format .`
Expected: `All checks passed!`,format 无改动或仅规范化。若有 `--fix` 可清的项,运行 `uv run ruff check --fix .`。

- [ ] **Step 3: 写 README**

Create `services/worker/README.md`:
```markdown
# Agent Cloud Worker

agent 的"脑":回合循环 + provider 抽象 + 工具接口。纯库,无网络/DB。

- `run_turn(provider, executor, system=, history=, user_message=)` — 跑一个回合。
- `Provider` / `FakeProvider` — LLM 抽象;真实 provider 在后续 Plan 接入。
- `ToolExecutor` / `LocalToolExecutor` — 工具执行抽象;gRPC 沙箱执行器在 Plan 2b 实现同一接口。
- `build_system_prompt(...)` — 文档/记忆/技能 → 分层 system 文本。

## 测试
```bash
cd services/worker && uv run pytest -v   # 纯单元测试,无需 Docker
```
```

- [ ] **Step 4: 全回归(worker + 不破坏 backend)**

Run worker suite: `cd services/worker && uv run pytest -v`
Expected: 全部 PASS(provider 2 + tools 5 + context 3 + loop 5 = 15)。

Run backend suite(确认未受影响): `cd services/backend && uv run pytest -q`
Expected: 25 passed。

- [ ] **Step 5: 提交**

```bash
git add services/worker/src/agent_cloud_worker/__init__.py services/worker/README.md
git commit -m "chore(worker): export public API and add README"
```

---

## Self-Review(写完后自检结果)

**Spec 覆盖(Plan 2a 范围)**:
- §4.2 worker = agent-loop + provider 抽象 + 工具决策 → `loop.run_turn` + `provider.Provider` + `tools.ToolExecutor`。✓
- §5.3 上下文组装(文档/记忆 → 分层) + §12 技能渐进式披露(注入 name/description/location)→ `context.build_system_prompt`(含 `<available_skills>`)。✓
- §8 回合循环(调 LLM → 工具 → 回填 → 终止)→ `run_turn`,含 max_iterations 守卫。✓
- §12 测试(假 LLM 保确定性;工具对真实临时目录)→ `FakeProvider` + `LocalToolExecutor`(真实 bash/文件,临时目录)。✓
- 明确延后(接缝已留):真实 provider、gRPC 沙箱执行器(实现 `ToolExecutor`)、后端编排、流式、会话锁。

**占位符扫描**:无 TBD;每步含完整代码与确切命令/预期。

**类型/命名一致性**:`run_turn(provider, executor, *, system, history, user_message, max_iterations=10)` 签名在测试与实现一致;`TurnResult.new_messages/usage/stop_reason`;`ToolExecutor.specs()/execute()` 被 loop 与 LocalToolExecutor 一致使用;`ToolCall.id/name/arguments`、`ToolResult.call_id/content/is_error`、`Message.role/text/tool_calls/tool_results`、`CompletionRequest/Result`、`Usage.input_tokens/output_tokens` 在 common 定义、worker 各处引用一致;`stop_reason` 取值 `"end_turn"|"max_iterations"` 与测试断言一致。
```
