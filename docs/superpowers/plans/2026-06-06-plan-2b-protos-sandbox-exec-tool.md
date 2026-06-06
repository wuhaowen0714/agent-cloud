# Plan 2b: protos + 沙箱 + exec_tool(worker↔sandbox 跳) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通 worker↔sandbox 的工具执行跳:定义 gRPC 契约(`exec_tool`)、生成桩到 `packages/common`、实现 `services/sandbox`(执行 bash/文件工具,带路径containment),并实现 `SandboxToolExecutor`(用 gRPC 调沙箱,满足 worker 已有的 `ToolExecutor` 接口)。端到端:`run_turn(FakeProvider, SandboxToolExecutor→真实本地沙箱服务)` 跨 gRPC 执行工具。

**Architecture:** 新建 workspace 成员 `services/sandbox`(包 `agent_cloud_sandbox`)。gRPC 契约源放 `protos/`,生成的 Python 桩落进 `packages/common`(随 common 分发,跨服务共享)。**工具的真实实现迁到沙箱**(它本就是工具执行处);worker 的 `LocalToolExecutor` 保留为单测替身。worker 新增 `SandboxToolExecutor`(gRPC 客户端,实现 `ToolExecutor` Protocol)。共享工具规格目录放 common(`builtin_tool_specs()`),这样 worker 无需依赖 sandbox 即可向 provider 广告工具。

**Tech Stack:** Python 3.12+、uv workspace、**grpcio + grpcio-tools**(gRPC,grpc.aio 异步)、pytest + pytest-asyncio + ruff。本计划仍用 `FakeProvider`(真实 LLM 在后续 Plan);**无需 Postgres/Docker**(沙箱在本地临时目录跑工具)。

参考:spec `docs/superpowers/specs/2026-06-05-stateless-agent-cloud-design.md`(§3.1 protos/common 布局、§6 协议、§7-③ exec_tool 契约、§11 卷隔离/containment)。Plan 2a 已合并:worker 有 `run_turn` / `Provider` / `ToolExecutor` / `LocalToolExecutor`;common 有领域类型。

## 范围

**做**:`protos/agent_cloud/v1/sandbox.proto`(`ExecTool` 一元 RPC)+ 代码生成(桩入 common)+ `scripts/gen_protos.sh`;common 的 `builtin_tool_specs()`;`services/sandbox`(工具实现 + containment + `run_tool` 分发 + gRPC 服务器);worker 的 `SandboxToolExecutor` + 跨 gRPC 的端到端测试。

**不做(后续)**:`run_turn` 的 gRPC 服务化、后端编排、会话锁、流式 stdout(本计划 exec_tool 为一元/非流式)、真实 LLM provider。这些是 Plan 2c+。

## File Structure

```
protos/agent_cloud/v1/sandbox.proto        # gRPC 契约源(语言中立)
scripts/gen_protos.sh                       # 代码生成脚本(可重复运行)
packages/common/
  pyproject.toml                            # +grpcio(运行时), dev +grpcio-tools; wheel 加 agent_cloud 包
  src/agent_cloud/__init__.py               # 生成桩的顶层包(machine-generated 容器)
  src/agent_cloud/v1/__init__.py
  src/agent_cloud/v1/sandbox_pb2.py         # 生成(提交)
  src/agent_cloud/v1/sandbox_pb2_grpc.py    # 生成(提交)
  src/agent_cloud_common/tools.py           # builtin_tool_specs()
services/sandbox/
  pyproject.toml                            # agent-cloud-sandbox(dep: common, grpcio)
  src/agent_cloud_sandbox/__init__.py
  src/agent_cloud_sandbox/tools.py          # 真实工具实现 + _resolve_within + run_tool 分发
  src/agent_cloud_sandbox/server.py         # SandboxServicer + create_server(...)
  tests/{__init__,test_tools,test_server}.py
services/worker/
  pyproject.toml                            # +grpcio(运行时); dev +agent-cloud-sandbox(e2e 起服务)
  src/agent_cloud_worker/sandbox_executor.py  # SandboxToolExecutor(实现 ToolExecutor)
  tests/test_sandbox_executor.py            # 端到端:run_turn 跨 gRPC 执行工具
```

> 桩的导入路径:proto 在 `protos/agent_cloud/v1/`,`-I protos` 生成到 `packages/common/src`,故生成 `agent_cloud/v1/sandbox_pb2*.py`,桩内为绝对导入 `from agent_cloud.v1 import sandbox_pb2`。`agent_cloud` 作为 common 分发内的第二个顶层包(只装生成桩),与 `agent_cloud_common`/`_backend`/`_worker` 不冲突。shell cwd 在命令间会保持,命令用绝对路径或单条 `cd /abs && ...`。

---

### Task 0: gRPC 依赖 + proto + 代码生成 + sandbox 包脚手架

**Files:**
- Create: `protos/agent_cloud/v1/sandbox.proto`, `scripts/gen_protos.sh`, `services/sandbox/pyproject.toml`, `services/sandbox/src/agent_cloud_sandbox/__init__.py`, `services/sandbox/tests/__init__.py`
- Modify: `packages/common/pyproject.toml`
- Generated (commit): `packages/common/src/agent_cloud/__init__.py`, `.../agent_cloud/v1/__init__.py`, `.../agent_cloud/v1/sandbox_pb2.py`, `.../sandbox_pb2_grpc.py`

- [ ] **Step 1: 写 proto**

Create `protos/agent_cloud/v1/sandbox.proto`:
```proto
syntax = "proto3";

package agent_cloud.v1;

// 沙箱:在工作目录里执行一次工具调用(worker→sandbox,信任边界)。
service Sandbox {
  rpc ExecTool(ExecToolRequest) returns (ExecToolResponse);
}

message ExecToolRequest {
  string call_id = 1;
  string tool_name = 2;
  string arguments_json = 3;  // JSON 编码的参数字典
  string work_subdir = 4;     // 相对沙箱基目录的会话工作子目录
}

message ExecToolResponse {
  string content = 1;
  bool is_error = 2;
}
```

- [ ] **Step 2: common 加 grpc 依赖并把生成桩纳入打包**

Edit `packages/common/pyproject.toml`:
- 在 `[project]` 的 `dependencies` 加 `"grpcio"`。
- 加一个 dev 组(若不存在则新增):
```toml
[dependency-groups]
dev = ["grpcio-tools"]
```
- 把 wheel 打包目标改为同时包含生成桩包:
```toml
[tool.hatch.build.targets.wheel]
packages = ["src/agent_cloud_common", "src/agent_cloud"]
```

- [ ] **Step 3: 写代码生成脚本**

Create `scripts/gen_protos.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
# 从仓库根运行。把 protos/ 下的 .proto 生成为 Python 桩,落进 packages/common/src。
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="packages/common/src"
uv run --package agent-cloud-common python -m grpc_tools.protoc \
  -I protos \
  --python_out="$OUT" \
  --grpc_python_out="$OUT" \
  protos/agent_cloud/v1/sandbox.proto
# 确保是常规包(可导入)
touch "$OUT/agent_cloud/__init__.py" "$OUT/agent_cloud/v1/__init__.py"
echo "generated stubs under $OUT/agent_cloud/v1/"
```
Make it executable: `chmod +x scripts/gen_protos.sh`.

- [ ] **Step 4: sandbox 包脚手架**

Create `services/sandbox/pyproject.toml`:
```toml
[project]
name = "agent-cloud-sandbox"
version = "0.0.0"
requires-python = ">=3.12"
dependencies = [
    "agent-cloud-common",
    "grpcio",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agent_cloud_sandbox"]

[tool.uv.sources]
agent-cloud-common = { workspace = true }

[dependency-groups]
dev = ["pytest", "pytest-asyncio", "ruff"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
pythonpath = ["src"]
```

Create empty `services/sandbox/src/agent_cloud_sandbox/__init__.py` and `services/sandbox/tests/__init__.py`.

- [ ] **Step 5: 同步 + 生成桩**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && uv sync && bash scripts/gen_protos.sh
```
Expected: `uv sync` 安装 grpcio/grpcio-tools 与新成员 sandbox;脚本生成 `packages/common/src/agent_cloud/v1/sandbox_pb2.py` 与 `sandbox_pb2_grpc.py`,并创建 `__init__.py`。

- [ ] **Step 6: 验证桩可导入**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run python -c "from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc; print(sandbox_pb2.ExecToolRequest(call_id='x').call_id, hasattr(sandbox_pb2_grpc, 'SandboxServicer'))"
```
Expected: 打印 `x True`,无导入错误。

- [ ] **Step 7: 提交**

```bash
git add protos scripts/gen_protos.sh packages/common/pyproject.toml packages/common/src/agent_cloud services/sandbox/pyproject.toml services/sandbox/src/agent_cloud_sandbox/__init__.py services/sandbox/tests/__init__.py uv.lock
git commit -m "chore(grpc): add sandbox proto, codegen, and sandbox package scaffold"
```

---

### Task 1: 共享工具规格目录(common)

**Files:**
- Create: `packages/common/src/agent_cloud_common/tools.py`
- Modify: `packages/common/src/agent_cloud_common/__init__.py`

> worker 要向 provider 广告工具,但工具实现在 sandbox。规格目录放 common,两边共享、互不依赖。

- [ ] **Step 1: 写 tools.py(规格目录)**

Create `packages/common/src/agent_cloud_common/tools.py`:
```python
from __future__ import annotations

from agent_cloud_common.types import ToolSpec


def builtin_tool_specs() -> list[ToolSpec]:
    """内置工具的对外规格(实现位于 sandbox 服务)。"""
    return [
        ToolSpec(
            name="bash",
            description="Run a shell command in the working directory.",
            input_schema={"type": "object",
                          "properties": {"command": {"type": "string"}},
                          "required": ["command"]},
        ),
        ToolSpec(
            name="write_file",
            description="Write text to a file (relative to the working directory).",
            input_schema={"type": "object",
                          "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                          "required": ["path", "content"]},
        ),
        ToolSpec(
            name="read_file",
            description="Read a file (relative to the working directory).",
            input_schema={"type": "object",
                          "properties": {"path": {"type": "string"}},
                          "required": ["path"]},
        ),
    ]
```

- [ ] **Step 2: 导出**

Edit `packages/common/src/agent_cloud_common/__init__.py`: add `from agent_cloud_common.tools import builtin_tool_specs` and add `"builtin_tool_specs"` to `__all__`.

- [ ] **Step 3: 冒烟**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run python -c "from agent_cloud_common import builtin_tool_specs; print([s.name for s in builtin_tool_specs()])"`
Expected: `['bash', 'write_file', 'read_file']`。

- [ ] **Step 4: 提交**

```bash
git add packages/common/src/agent_cloud_common/tools.py packages/common/src/agent_cloud_common/__init__.py
git commit -m "feat(common): add builtin tool spec catalog"
```

---

### Task 2: 沙箱工具实现 + containment + run_tool 分发

**Files:**
- Create: `services/sandbox/src/agent_cloud_sandbox/tools.py`
- Test: `services/sandbox/tests/test_tools.py`

- [ ] **Step 1: 写失败测试**

Create `services/sandbox/tests/test_tools.py`:
```python
from agent_cloud_sandbox.tools import run_tool


def test_write_then_read(tmp_path):
    content, err = run_tool(tmp_path, "s1", "write_file",
                            '{"path": "a.txt", "content": "hello"}')
    assert err is False
    content, err = run_tool(tmp_path, "s1", "read_file", '{"path": "a.txt"}')
    assert err is False and content == "hello"
    # 写到了 base/work_subdir 下
    assert (tmp_path / "s1" / "a.txt").read_text() == "hello"


def test_bash_runs_in_workdir(tmp_path):
    content, err = run_tool(tmp_path, "s1", "bash", '{"command": "echo hi"}')
    assert err is False and "hi" in content


def test_bash_nonzero_is_error(tmp_path):
    _, err = run_tool(tmp_path, "s1", "bash", '{"command": "exit 7"}')
    assert err is True


def test_unknown_tool(tmp_path):
    content, err = run_tool(tmp_path, "s1", "nope", "{}")
    assert err is True and "unknown tool" in content.lower()


def test_missing_argument_friendly(tmp_path):
    content, err = run_tool(tmp_path, "s1", "write_file", '{"path": "a.txt"}')
    assert err is True and "missing required argument" in content


def test_invalid_json(tmp_path):
    content, err = run_tool(tmp_path, "s1", "bash", "{not json")
    assert err is True and "invalid arguments_json" in content


def test_path_traversal_rejected(tmp_path):
    content, err = run_tool(tmp_path, "s1", "write_file",
                            '{"path": "../escape.txt", "content": "x"}')
    assert err is True and "escapes working directory" in content
    assert not (tmp_path / "escape.txt").exists()


def test_absolute_path_rejected(tmp_path):
    _, err = run_tool(tmp_path, "s1", "read_file", '{"path": "/etc/hosts"}')
    assert err is True
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run pytest tests/test_tools.py -v`
Expected: FAIL(`ModuleNotFoundError: agent_cloud_sandbox.tools`)。

- [ ] **Step 3: 写 tools.py**

Create `services/sandbox/src/agent_cloud_sandbox/tools.py`:
```python
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path


def _resolve_within(workdir: Path, path: str) -> Path:
    candidate = (workdir / path).resolve()
    if not candidate.is_relative_to(workdir.resolve()):
        raise ValueError(f"path escapes working directory: {path}")
    return candidate


# bash 执行任意命令;进程/文件系统隔离由真实部署的沙箱(microVM/gVisor + cgroups,
# spec §11)负责,不是这段本地实现的职责。
def _bash(workdir: Path, args: dict) -> str:
    proc = subprocess.run(
        args["command"], shell=True, cwd=workdir, capture_output=True, text=True
    )
    output = proc.stdout + proc.stderr
    if proc.returncode != 0:
        raise RuntimeError(f"exit {proc.returncode}: {output}")
    return output


def _write_file(workdir: Path, args: dict) -> str:
    content = args["content"]  # 先取,缺失则在写盘前就报错
    target = _resolve_within(workdir, args["path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return f"wrote {args['path']}"


def _read_file(workdir: Path, args: dict) -> str:
    return _resolve_within(workdir, args["path"]).read_text()


_TOOLS: dict[str, Callable[[Path, dict], str]] = {
    "bash": _bash,
    "write_file": _write_file,
    "read_file": _read_file,
}


def run_tool(
    base_workdir: Path, work_subdir: str, tool_name: str, arguments_json: str
) -> tuple[str, bool]:
    """执行一次工具调用,返回 (content, is_error)。"""
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as exc:
        return (f"invalid arguments_json: {exc}", True)

    workdir = Path(base_workdir) / work_subdir
    workdir.mkdir(parents=True, exist_ok=True)

    func = _TOOLS.get(tool_name)
    if func is None:
        return (f"unknown tool: {tool_name}", True)
    try:
        return (func(workdir, args), False)
    except KeyError as exc:
        return (f"missing required argument: {exc.args[0]}", True)
    except Exception as exc:
        return (str(exc), True)
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run pytest tests/test_tools.py -v`
Expected: PASS(8 passed)。

- [ ] **Step 5: 提交**

```bash
git add services/sandbox/src/agent_cloud_sandbox/tools.py services/sandbox/tests/test_tools.py
git commit -m "feat(sandbox): add tool implementations with path containment and run_tool dispatch"
```

---

### Task 3: 沙箱 gRPC 服务器

**Files:**
- Create: `services/sandbox/src/agent_cloud_sandbox/server.py`
- Test: `services/sandbox/tests/test_server.py`

- [ ] **Step 1: 写失败测试(对真实 aio 服务器发 RPC)**

Create `services/sandbox/tests/test_server.py`:
```python
import grpc
import pytest_asyncio

from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc
from agent_cloud_sandbox.server import create_server


@pytest_asyncio.fixture
async def sandbox(tmp_path):
    server, port = await create_server(base_workdir=tmp_path, host="localhost", port=0)
    yield f"localhost:{port}", tmp_path
    await server.stop(None)


async def test_exec_tool_over_grpc(sandbox):
    addr, base = sandbox
    async with grpc.aio.insecure_channel(addr) as channel:
        stub = sandbox_pb2_grpc.SandboxStub(channel)
        resp = await stub.ExecTool(sandbox_pb2.ExecToolRequest(
            call_id="c1", tool_name="write_file",
            arguments_json='{"path": "out.txt", "content": "data"}',
            work_subdir="s1",
        ))
    assert resp.is_error is False
    assert (base / "s1" / "out.txt").read_text() == "data"


async def test_exec_tool_error_over_grpc(sandbox):
    addr, _ = sandbox
    async with grpc.aio.insecure_channel(addr) as channel:
        stub = sandbox_pb2_grpc.SandboxStub(channel)
        resp = await stub.ExecTool(sandbox_pb2.ExecToolRequest(
            call_id="c1", tool_name="nope", arguments_json="{}", work_subdir="s1",
        ))
    assert resp.is_error is True
    assert "unknown tool" in resp.content.lower()
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run pytest tests/test_server.py -v`
Expected: FAIL(`ImportError`/`ModuleNotFoundError: agent_cloud_sandbox.server`)。

- [ ] **Step 3: 写 server.py**

Create `services/sandbox/src/agent_cloud_sandbox/server.py`:
```python
from __future__ import annotations

from pathlib import Path

import grpc

from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc
from agent_cloud_sandbox.tools import run_tool


class SandboxServicer(sandbox_pb2_grpc.SandboxServicer):
    def __init__(self, base_workdir: Path) -> None:
        self._base = Path(base_workdir)

    async def ExecTool(
        self, request: sandbox_pb2.ExecToolRequest, context: grpc.aio.ServicerContext
    ) -> sandbox_pb2.ExecToolResponse:
        content, is_error = run_tool(
            self._base, request.work_subdir, request.tool_name, request.arguments_json
        )
        return sandbox_pb2.ExecToolResponse(content=content, is_error=is_error)


async def create_server(
    base_workdir: Path, host: str = "localhost", port: int = 0
) -> tuple[grpc.aio.Server, int]:
    """创建并启动一个 aio gRPC 服务器,返回 (server, bound_port)。port=0 让系统分配。"""
    server = grpc.aio.server()
    sandbox_pb2_grpc.add_SandboxServicer_to_server(SandboxServicer(base_workdir), server)
    bound_port = server.add_insecure_port(f"{host}:{port}")
    await server.start()
    return server, bound_port
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run pytest -v`
Expected: PASS(tools 8 + server 2 = 10 passed)。

- [ ] **Step 5: 提交**

```bash
git add services/sandbox/src/agent_cloud_sandbox/server.py services/sandbox/tests/test_server.py
git commit -m "feat(sandbox): add aio gRPC ExecTool server"
```

---

### Task 4: worker 的 SandboxToolExecutor + 端到端

**Files:**
- Modify: `services/worker/pyproject.toml`(+grpcio 运行时;dev +agent-cloud-sandbox)
- Create: `services/worker/src/agent_cloud_worker/sandbox_executor.py`
- Test: `services/worker/tests/test_sandbox_executor.py`

- [ ] **Step 1: worker 加依赖**

Edit `services/worker/pyproject.toml`:
- `[project].dependencies` 加 `"grpcio"`。
- `[dependency-groups].dev` 加 `"agent-cloud-sandbox"`(端到端测试需起真实沙箱服务)。
- 在 `[tool.uv.sources]` 加 `agent-cloud-sandbox = { workspace = true }`。

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud && uv sync`
Expected: worker 环境含 grpcio 与(dev)agent-cloud-sandbox。

- [ ] **Step 2: 写失败测试(端到端:run_turn 跨 gRPC 执行工具)**

Create `services/worker/tests/test_sandbox_executor.py`:
```python
import grpc
import pytest_asyncio

from agent_cloud_common import CompletionResult, Message, Role, ToolCall, Usage
from agent_cloud_sandbox.server import create_server
from agent_cloud_worker.loop import run_turn
from agent_cloud_worker.provider import FakeProvider
from agent_cloud_worker.sandbox_executor import SandboxToolExecutor


@pytest_asyncio.fixture
async def sandbox(tmp_path):
    server, port = await create_server(base_workdir=tmp_path, host="localhost", port=0)
    yield f"localhost:{port}", tmp_path
    await server.stop(None)


def _call(tool, args):
    return CompletionResult(
        message=Message(role=Role.ASSISTANT,
                        tool_calls=[ToolCall(id="c1", name=tool, arguments=args)]),
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def _final(text):
    return CompletionResult(message=Message(role=Role.ASSISTANT, text=text),
                            usage=Usage(input_tokens=1, output_tokens=1))


async def test_specs_match_catalog(sandbox):
    addr, _ = sandbox
    async with grpc.aio.insecure_channel(addr) as channel:
        ex = SandboxToolExecutor(channel, work_subdir="s1")
        assert {s.name for s in ex.specs()} == {"bash", "write_file", "read_file"}


async def test_run_turn_executes_tool_across_grpc(sandbox):
    addr, base = sandbox
    provider = FakeProvider([
        _call("write_file", {"path": "hello.txt", "content": "from-agent"}),
        _final("done"),
    ])
    async with grpc.aio.insecure_channel(addr) as channel:
        ex = SandboxToolExecutor(channel, work_subdir="s1")
        result = await run_turn(provider, ex, system="", history=[], user_message="write it")
    assert result.stop_reason == "end_turn"
    assert [m.role for m in result.new_messages] == [Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]
    assert result.new_messages[1].tool_results[0].is_error is False
    # 工具真的在沙箱的 work_subdir 下执行了
    assert (base / "s1" / "hello.txt").read_text() == "from-agent"
```

- [ ] **Step 3: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_sandbox_executor.py -v`
Expected: FAIL(`ModuleNotFoundError: agent_cloud_worker.sandbox_executor`)。

- [ ] **Step 4: 写 sandbox_executor.py**

Create `services/worker/src/agent_cloud_worker/sandbox_executor.py`:
```python
from __future__ import annotations

import json

import grpc

from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc
from agent_cloud_common import ToolCall, ToolResult, ToolSpec, builtin_tool_specs


class SandboxToolExecutor:
    """ToolExecutor 实现:把工具调用通过 gRPC 下发给沙箱服务执行。

    这是 worker→sandbox 信任边界的客户端侧:只传 工具名 + 参数 + 工作目录,
    不传 LLM Key。
    """

    def __init__(self, channel: grpc.aio.Channel, work_subdir: str) -> None:
        self._stub = sandbox_pb2_grpc.SandboxStub(channel)
        self._work_subdir = work_subdir

    def specs(self) -> list[ToolSpec]:
        return builtin_tool_specs()

    async def execute(self, call: ToolCall) -> ToolResult:
        resp = await self._stub.ExecTool(
            sandbox_pb2.ExecToolRequest(
                call_id=call.id,
                tool_name=call.name,
                arguments_json=json.dumps(call.arguments),
                work_subdir=self._work_subdir,
            )
        )
        return ToolResult(call_id=call.id, content=resp.content, is_error=resp.is_error)
```

- [ ] **Step 5: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_sandbox_executor.py -v`
Expected: PASS(2 passed)。

- [ ] **Step 6: 提交**

```bash
git add services/worker/pyproject.toml services/worker/src/agent_cloud_worker/sandbox_executor.py services/worker/tests/test_sandbox_executor.py uv.lock
git commit -m "feat(worker): add SandboxToolExecutor (ToolExecutor over gRPC) with e2e test"
```

---

### Task 5: 导出 + lint + README + 全回归

**Files:**
- Modify: `services/worker/src/agent_cloud_worker/__init__.py`(导出 SandboxToolExecutor)
- Create: `services/sandbox/README.md`

- [ ] **Step 1: 导出 SandboxToolExecutor**

Edit `services/worker/src/agent_cloud_worker/__init__.py`: add `from agent_cloud_worker.sandbox_executor import SandboxToolExecutor` and add `"SandboxToolExecutor"` to `__all__`.

- [ ] **Step 2: 写 sandbox README**

Create `services/sandbox/README.md`:
```markdown
# Agent Cloud Sandbox

执行工具调用的 gRPC 服务(worker→sandbox 信任边界)。只暴露 `ExecTool`。

- `agent_cloud_sandbox.tools.run_tool(base, work_subdir, name, args_json)` — 执行一次工具(bash/write_file/read_file),带路径 containment。
- `agent_cloud_sandbox.server.create_server(base_workdir, host, port)` — 启动 aio gRPC 服务器。
- 契约见 `protos/agent_cloud/v1/sandbox.proto`;桩生成到 packages/common(`scripts/gen_protos.sh`)。
- 真实进程/文件系统隔离(microVM/gVisor + cgroups + egress)由部署层负责(spec §11),非本服务代码。

## 测试
```bash
cd services/sandbox && uv run pytest -v
```
```

- [ ] **Step 3: lint(各包)**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run ruff check . && uv run ruff format .
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run ruff check . && uv run ruff format .
```
Expected: `All checks passed!`。注:不要对 `packages/common/src/agent_cloud/`(生成桩)做 lint——生成代码豁免;若 ruff 报到它,运行 worker/sandbox 的 lint 时它们不在范围内即可(各自 `cd` 到服务目录跑)。

- [ ] **Step 4: 全回归**

Run(三套):
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest -q
```
Expected: sandbox 10 passed;worker 27 passed(2a 的 25 + 本计划 2);backend 25 passed。

- [ ] **Step 5: 提交**

```bash
git add services/worker/src/agent_cloud_worker/__init__.py services/sandbox/README.md
git commit -m "chore: export SandboxToolExecutor and add sandbox README"
```

---

## Self-Review(写完后自检结果)

**Spec 覆盖(Plan 2b 范围)**:
- §6/§7-③ exec_tool gRPC 契约(仅暴露一个面)→ `sandbox.proto` 的 `ExecTool`;桩入 common(§3.1)。✓
- §11 containment(沙箱只在工作子目录内动文件)→ `_resolve_within`,拒绝 `../` 与绝对路径。✓
- worker↔sandbox 信任边界(只传 名/参/目录,不传 Key)→ `SandboxToolExecutor` 的 `ExecToolRequest`。✓
- worker 的 `ToolExecutor` 接口被真实跨 gRPC 实现 → `SandboxToolExecutor.specs()/execute()`;端到端 `run_turn` 测试穿过 gRPC。✓
- 工具实现迁到 sandbox;worker `LocalToolExecutor` 留作替身;规格目录入 common 供 worker 广告。✓
- 明确延后:`run_turn` 服务化、后端编排、流式 stdout、真实 provider(Plan 2c+)。

**占位符扫描**:无 TBD。生成桩(`sandbox_pb2*.py`)由 `scripts/gen_protos.sh` 产出并提交,不在计划里逐字粘贴(机器生成);其余每步均有完整代码或确切命令/预期。

**类型/命名一致性**:proto 包 `agent_cloud.v1`,Python 导入 `from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc` 在 sandbox/worker 一致;`ExecToolRequest(call_id, tool_name, arguments_json, work_subdir)` / `ExecToolResponse(content, is_error)` 字段在 proto、server、executor 一致;`run_tool(base_workdir, work_subdir, tool_name, arguments_json) -> (content, is_error)`;`create_server(base_workdir, host, port) -> (server, bound_port)`;`SandboxToolExecutor(channel, work_subdir)` 实现 worker `ToolExecutor` 的 `specs()/execute()`;`builtin_tool_specs()` 在 common 定义、worker executor 引用。
```
