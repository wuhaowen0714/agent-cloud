# Plan 2c: worker gRPC 服务器(RunTurn) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Plan 2a 的 `run_turn` 循环包成 gRPC 服务:定义结构化 `worker.proto`(`RunTurn`)、common 里的 dataclass↔proto 转换器,以及 worker 服务器(组装 system prompt、拨号沙箱、跑 `run_turn`、回传结果)。端到端:`RunTurn` over gRPC + 真实沙箱执行工具(无需 DB)。

**Architecture:** `worker.proto` 定义结构化的 `RunTurnRequest/Response`(agent + 上下文[文档/记忆/技能/历史] + 用户消息 + 沙箱端点/工作目录 → 新消息 + usage + stop_reason),桩生成进 `packages/common`。common 加 `codec`(Message↔proto,backend 在 2d 也会用)。worker 加 `server.py`:`WorkerServicer.RunTurn` 解码请求 → `build_system_prompt` → 拨号 `sandbox_endpoint` 建 `SandboxToolExecutor` → 用注入的 `provider`(测试用 FakeProvider)跑 `run_turn` → 编码回 proto。Provider 用工厂注入(真实 LLM provider 留待后续 Plan)。

**Tech Stack:** Python 3.12+、uv workspace、grpcio(grpc.aio)、pytest + pytest-asyncio + ruff。仍用 FakeProvider;**无需 Postgres/Docker**(e2e 起内嵌 worker + sandbox aio 服务器)。

参考:spec `docs/superpowers/specs/2026-06-05-stateless-agent-cloud-design.md`(§4.2、§6、§7-①④ run_turn 契约、§8)。已合并:Plan 2a(`run_turn`/`build_system_prompt`/`FakeProvider`)、2b(`SandboxToolExecutor`、`create_server` 沙箱、生成桩管线 `scripts/gen_protos.sh`)。

## 范围

**做**:`protos/agent_cloud/v1/worker.proto` + 扩展 gen 脚本生成它;common `codec`(Message↔proto)+ 测试;worker `server.py`(`WorkerServicer` + `create_server`)+ e2e 测试(worker+sandbox);导出/README/lint。

**不做(Plan 2d)**:后端回合编排(会话锁、从 DB 组装上下文、落库)、真实 LLM provider、流式。

## File Structure

```
protos/agent_cloud/v1/worker.proto              # 结构化 RunTurn 契约
scripts/gen_protos.sh                           # 扩展为生成所有 protos
packages/common/src/agent_cloud/v1/worker_pb2.py / worker_pb2_grpc.py   # 生成(提交)
packages/common/src/agent_cloud_common/codec.py # Message↔proto 转换(显式子模块,不入 __init__)
services/worker/src/agent_cloud_worker/server.py # WorkerServicer + create_server
services/worker/tests/{test_codec? no -> in common}/...
packages/common/tests/test_codec.py             # codec round-trip(common 首个测试)
services/worker/tests/test_worker_server.py      # e2e:RunTurn over gRPC + 真沙箱
```

> codec 放 common(backend 在 2d 也用),但不加进 `agent_cloud_common/__init__`(避免 `import agent_cloud_common` 牵入 grpc);显式 `from agent_cloud_common.codec import msg_to_proto`。common 本计划首次拥有测试,需给 common 加 dev 测试依赖与 pytest 配置。shell cwd 在命令间保持,用绝对路径。

---

### Task 0: worker.proto + 代码生成

**Files:**
- Create: `protos/agent_cloud/v1/worker.proto`
- Modify: `scripts/gen_protos.sh`
- Generated (commit): `packages/common/src/agent_cloud/v1/worker_pb2.py`, `.../worker_pb2_grpc.py`

- [ ] **Step 1: 写 worker.proto**

Create `protos/agent_cloud/v1/worker.proto`:
```proto
syntax = "proto3";

package agent_cloud.v1;

// worker:跑一个回合(后端→worker)。本计划为一元(非流式);流式见后续 Plan。
service Worker {
  rpc RunTurn(RunTurnRequest) returns (RunTurnResponse);
}

message ToolCall {
  string id = 1;
  string name = 2;
  string arguments_json = 3;
}

message ToolResult {
  string call_id = 1;
  string content = 2;
  bool is_error = 3;
}

message Msg {
  string role = 1;  // user | assistant | tool
  string text = 2;
  repeated ToolCall tool_calls = 3;
  repeated ToolResult tool_results = 4;
}

message Agent {
  string model = 1;
  string provider = 2;
  string thinking_level = 3;
  repeated string enabled_tools = 4;
  string key_ref = 5;
}

message Doc {
  string scope = 1;
  string type = 2;
  string content = 3;
}

message Mem {
  string scope = 1;
  string content = 2;
}

message Skill {
  string name = 1;
  string description = 2;
  string location = 3;
}

message RunTurnRequest {
  string session_id = 1;
  string user_id = 2;
  Agent agent = 3;
  repeated Doc documents = 4;
  repeated Mem memory = 5;
  repeated Skill skills = 6;
  repeated Msg messages = 7;   // 历史
  string user_message = 8;
  string sandbox_endpoint = 9;
  string work_subdir = 10;
}

message RunTurnResponse {
  repeated Msg new_messages = 1;
  int64 input_tokens = 2;
  int64 output_tokens = 3;
  string stop_reason = 4;
}
```

- [ ] **Step 2: 扩展 gen 脚本生成所有 protos**

Replace `scripts/gen_protos.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
# 从仓库根运行。把 protos/ 下所有 .proto 生成为 Python 桩,落进 packages/common/src。
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="packages/common/src"
uv run --package agent-cloud-common python -m grpc_tools.protoc \
  -I protos \
  --python_out="$OUT" \
  --grpc_python_out="$OUT" \
  protos/agent_cloud/v1/sandbox.proto \
  protos/agent_cloud/v1/worker.proto
touch "$OUT/agent_cloud/__init__.py" "$OUT/agent_cloud/v1/__init__.py"
echo "generated stubs under $OUT/agent_cloud/v1/"
```

- [ ] **Step 3: 生成**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud && bash scripts/gen_protos.sh`
Expected: 生成 `worker_pb2.py` 与 `worker_pb2_grpc.py`(sandbox 的也会重新生成,内容不变)。

- [ ] **Step 4: 验证导入**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run python -c "from agent_cloud.v1 import worker_pb2, worker_pb2_grpc; print(worker_pb2.RunTurnRequest(user_message='hi').user_message, hasattr(worker_pb2_grpc,'WorkerServicer'))"`
Expected: 打印 `hi True`。若桩内是裸 `import worker_pb2`(相对)导致失败,STOP 报 BLOCKED(同 2b 的处理)。

- [ ] **Step 5: 提交**

```bash
git add protos/agent_cloud/v1/worker.proto scripts/gen_protos.sh packages/common/src/agent_cloud/v1/worker_pb2.py packages/common/src/agent_cloud/v1/worker_pb2_grpc.py
git commit -m "chore(grpc): add worker RunTurn proto and codegen"
```

---

### Task 1: common codec(Message↔proto)

**Files:**
- Create: `packages/common/src/agent_cloud_common/codec.py`, `packages/common/tests/__init__.py`, `packages/common/tests/test_codec.py`
- Modify: `packages/common/pyproject.toml`(加 dev 测试依赖 + pytest 配置)

- [ ] **Step 1: 给 common 加测试依赖与 pytest 配置**

Edit `packages/common/pyproject.toml`:
- 把 `[dependency-groups].dev` 改为(保留 grpcio-tools,加 pytest):
```toml
[dependency-groups]
dev = ["grpcio-tools", "pytest"]
```
- 加(若不存在):
```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
```

- [ ] **Step 2: 写 codec 失败测试**

Create `packages/common/tests/__init__.py`(空)。

Create `packages/common/tests/test_codec.py`:
```python
from agent_cloud_common.codec import msg_from_proto, msg_to_proto
from agent_cloud_common.types import Message, Role, ToolCall, ToolResult


def test_round_trip_assistant_with_tool_calls():
    m = Message(role=Role.ASSISTANT, text="hi",
                tool_calls=[ToolCall(id="c1", name="bash", arguments={"command": "echo x"})])
    back = msg_from_proto(msg_to_proto(m))
    assert back.role == Role.ASSISTANT
    assert back.text == "hi"
    assert back.tool_calls[0].id == "c1"
    assert back.tool_calls[0].name == "bash"
    assert back.tool_calls[0].arguments == {"command": "echo x"}
    assert back.tool_results == []


def test_round_trip_tool_message():
    m = Message(role=Role.TOOL,
                tool_results=[ToolResult(call_id="c1", content="out", is_error=False),
                              ToolResult(call_id="c2", content="boom", is_error=True)])
    back = msg_from_proto(msg_to_proto(m))
    assert back.role == Role.TOOL
    assert [r.call_id for r in back.tool_results] == ["c1", "c2"]
    assert back.tool_results[1].is_error is True


def test_round_trip_plain_user():
    m = Message(role=Role.USER, text="hello")
    back = msg_from_proto(msg_to_proto(m))
    assert back.role == Role.USER and back.text == "hello"
    assert back.tool_calls == [] and back.tool_results == []
```

- [ ] **Step 3: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/packages/common && uv run pytest tests/test_codec.py -v`
Expected: FAIL(`ModuleNotFoundError: agent_cloud_common.codec`)。

- [ ] **Step 4: 写 codec.py**

Create `packages/common/src/agent_cloud_common/codec.py`:
```python
from __future__ import annotations

import json

from agent_cloud.v1 import worker_pb2

from agent_cloud_common.types import Message, Role, ToolCall, ToolResult


def msg_to_proto(message: Message) -> worker_pb2.Msg:
    return worker_pb2.Msg(
        role=message.role.value,
        text=message.text,
        tool_calls=[
            worker_pb2.ToolCall(id=c.id, name=c.name, arguments_json=json.dumps(c.arguments))
            for c in message.tool_calls
        ],
        tool_results=[
            worker_pb2.ToolResult(call_id=r.call_id, content=r.content, is_error=r.is_error)
            for r in message.tool_results
        ],
    )


def msg_from_proto(proto: worker_pb2.Msg) -> Message:
    return Message(
        role=Role(proto.role),
        text=proto.text,
        tool_calls=[
            ToolCall(id=c.id, name=c.name, arguments=json.loads(c.arguments_json or "{}"))
            for c in proto.tool_calls
        ],
        tool_results=[
            ToolResult(call_id=r.call_id, content=r.content, is_error=r.is_error)
            for r in proto.tool_results
        ],
    )
```

- [ ] **Step 5: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/packages/common && uv run pytest tests/test_codec.py -v`
Expected: PASS(3 passed)。

- [ ] **Step 6: 提交**

```bash
git add packages/common/pyproject.toml packages/common/tests packages/common/src/agent_cloud_common/codec.py
git commit -m "feat(common): add Message<->proto codec"
```

---

### Task 2: worker gRPC 服务器(RunTurn)+ 端到端

**Files:**
- Create: `services/worker/src/agent_cloud_worker/server.py`
- Test: `services/worker/tests/test_worker_server.py`

- [ ] **Step 1: 写 e2e 失败测试(RunTurn over gRPC + 真沙箱)**

Create `services/worker/tests/test_worker_server.py`:
```python
import grpc
import pytest_asyncio

from agent_cloud.v1 import worker_pb2, worker_pb2_grpc
from agent_cloud_common import CompletionResult, Message, Role, ToolCall, Usage
from agent_cloud_sandbox.server import create_server as create_sandbox_server
from agent_cloud_worker.provider import FakeProvider
from agent_cloud_worker.server import create_server as create_worker_server


@pytest_asyncio.fixture
async def sandbox(tmp_path):
    server, port = await create_sandbox_server(base_workdir=tmp_path, host="localhost", port=0)
    yield f"localhost:{port}", tmp_path
    await server.stop(None)


def _call(tool, args):
    return CompletionResult(
        message=Message(role=Role.ASSISTANT,
                        tool_calls=[ToolCall(id="c1", name=tool, arguments=args)]),
        usage=Usage(input_tokens=3, output_tokens=4),
    )


def _final(text):
    return CompletionResult(message=Message(role=Role.ASSISTANT, text=text),
                            usage=Usage(input_tokens=3, output_tokens=4))


async def test_run_turn_over_grpc_executes_tool(sandbox):
    sandbox_addr, base = sandbox
    provider = FakeProvider([
        _call("write_file", {"path": "hello.txt", "content": "from-agent"}),
        _final("done"),
    ])
    worker_server, wport = await create_worker_server(
        provider_factory=lambda model, provider_name, key_ref: provider,
        host="localhost", port=0,
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            resp = await stub.RunTurn(worker_pb2.RunTurnRequest(
                session_id="s1", user_id="u1",
                agent=worker_pb2.Agent(model="m", provider="fake"),
                documents=[worker_pb2.Doc(scope="user", type="USER", content="# u")],
                messages=[],
                user_message="write the file",
                sandbox_endpoint=sandbox_addr,
                work_subdir="s1",
            ))
    finally:
        await worker_server.stop(None)

    assert resp.stop_reason == "end_turn"
    assert [m.role for m in resp.new_messages] == ["assistant", "tool", "assistant"]
    assert resp.output_tokens == 8  # 两次 provider 调用累加
    assert (base / "s1" / "hello.txt").read_text() == "from-agent"


async def test_run_turn_history_passed_through(sandbox):
    sandbox_addr, _ = sandbox
    provider = FakeProvider([_final("ok")])
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider, host="localhost", port=0,
    )
    try:
        async with grpc.aio.insecure_channel(f"localhost:{wport}") as channel:
            stub = worker_pb2_grpc.WorkerStub(channel)
            resp = await stub.RunTurn(worker_pb2.RunTurnRequest(
                agent=worker_pb2.Agent(model="m", provider="fake"),
                messages=[worker_pb2.Msg(role="user", text="earlier"),
                          worker_pb2.Msg(role="assistant", text="reply")],
                user_message="now", sandbox_endpoint=sandbox_addr, work_subdir="s1",
            ))
    finally:
        await worker_server.stop(None)
    assert resp.stop_reason == "end_turn"
    assert len(resp.new_messages) == 1 and resp.new_messages[0].text == "ok"
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_worker_server.py -v`
Expected: FAIL(`ModuleNotFoundError: agent_cloud_worker.server`)。

- [ ] **Step 3: 写 server.py**

Create `services/worker/src/agent_cloud_worker/server.py`:
```python
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
                provider, executor,
                system=system, history=history, user_message=request.user_message,
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
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_worker_server.py -v`
Expected: PASS(2 passed)。

- [ ] **Step 5: 提交**

```bash
git add services/worker/src/agent_cloud_worker/server.py services/worker/tests/test_worker_server.py
git commit -m "feat(worker): add RunTurn gRPC server with e2e sandbox test"
```

---

### Task 3: 导出 + README + lint + 全回归

**Files:**
- Modify: `services/worker/src/agent_cloud_worker/__init__.py`(导出 WorkerServicer/create_server)
- Modify: `services/worker/README.md`

- [ ] **Step 1: 导出**

Edit `services/worker/src/agent_cloud_worker/__init__.py`:
- 加 `from agent_cloud_worker.server import WorkerServicer, create_server`
- 在 `__all__` 加 `"WorkerServicer"`、`"create_server"`。

- [ ] **Step 2: README 追加**

在 `services/worker/README.md` 末尾追加:
```markdown

## gRPC 服务器(Plan 2c)
- `agent_cloud_worker.server.create_server(provider_factory, host, port)` — 启动 `Worker` aio gRPC 服务,实现 `RunTurn`。
- 契约:`protos/agent_cloud/v1/worker.proto`(`RunTurnRequest/Response`)。
- `provider_factory(model, provider, key_ref) -> Provider`:由 agent 配置造 provider(真实 LLM provider 后续接入)。
- 后端编排(会话锁/上下文组装/落库)见 Plan 2d。
```

- [ ] **Step 3: lint**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run ruff check . && uv run ruff format .
```
Expected: `All checks passed!`。(不对 `packages/common/src/agent_cloud/` 生成桩做 lint;codec.py 是手写的,纳入 common 的 lint——如需可 `cd packages/common && uv run ruff check src/agent_cloud_common`。)

- [ ] **Step 4: 全回归**

Run(四套):
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/packages/common && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest -q
```
Expected:common 3 passed;sandbox 23 passed;worker 32 passed(2b 的 30 + 本计划 2);backend 25 passed。

- [ ] **Step 5: 提交**

```bash
git add services/worker/src/agent_cloud_worker/__init__.py services/worker/README.md
git commit -m "chore(worker): export RunTurn server and document it"
```

---

## Self-Review(写完后自检结果)

**Spec 覆盖(Plan 2c 范围)**:
- §6/§7-①④ run_turn gRPC 契约(后端→worker)→ `worker.proto` 的 `RunTurn`,结构化 request/response;桩入 common(§3.1)。✓
- §8 worker 职责:组装 system(§5.3 文档/记忆/技能)+ 拨号沙箱 + 跑 run_turn + 回传新消息/usage/stop_reason → `WorkerServicer.RunTurn`。✓
- worker→sandbox 复用 2b 的 `SandboxToolExecutor`;Message↔proto 经 common `codec`(2d 后端复用)。✓
- provider 工厂注入,FakeProvider 驱动确定性 e2e;真实 provider 留待后续。✓
- 明确延后:后端编排/会话锁/落库(2d)、真实 provider、流式。

**占位符扫描**:无 TBD。生成桩由 `scripts/gen_protos.sh` 产出并提交,不逐字粘贴;其余每步有完整代码或确切命令/预期。

**类型/命名一致性**:proto 包 `agent_cloud.v1`,导入 `from agent_cloud.v1 import worker_pb2, worker_pb2_grpc`;`RunTurnRequest`(session_id/user_id/agent/documents/memory/skills/messages/user_message/sandbox_endpoint/work_subdir)与 `RunTurnResponse`(new_messages/input_tokens/output_tokens/stop_reason)字段在 proto、server、测试一致;`msg_to_proto/msg_from_proto` 在 common 定义、worker server 引用;`create_server(provider_factory, host, port) -> (server, bound_port)`;`ProviderFactory = Callable[[str,str,str], Provider]` 与测试的 `lambda model, provider_name, key_ref: provider` 一致;复用 2a 的 `run_turn(provider, executor, *, system, history, user_message)` 与 2b 的 `SandboxToolExecutor(channel, work_subdir)`。
```
