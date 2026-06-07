# Plan 5b: Skill 回合集成(物化进沙箱 + 元数据注入 + 按 agent 过滤工具)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让每个回合把「该会话所属 agent 已启用的 skill」物化进沙箱、把元数据注入 worker prompt,使 agent 能读 SKILL.md 并跑脚本;同时让 worker 按 `agent.enabled_tools` 过滤暴露给 LLM 的工具。

**Architecture:** 沙箱是**每用户一个**、被该用户的多个 agent/并发会话共用;但 skill 与 tool 都是**每 agent-config** 的。因此按**会话(work_subdir,天然绑定一个 agent)**隔离:回合开始把该会话 agent 的已启用 skill 从对象存储(Plan 5a)解包到 `<sandbox_base>/<user_id>/<work_subdir>/.skills/<name>/`(每回合先清空再重铺 = 天然失效,不同 agent 的并发会话互不干扰);`location` 用相对路径 `.skills/<name>/SKILL.md`,正好落在沙箱工具的 `work_subdir` 容器内,agent 用现有 `read_file`/`bash` 即可访问。worker 侧 `<available_skills>` 注入(`context.build_system_prompt`)与 proto `RunTurnRequest.skills` **已存在**,只需后端填充。tool 过滤在 worker 的 `SandboxToolExecutor.specs()` 按 `enabled_tools` 收窄(空=全部,兼容现有)。

**Tech Stack:** FastAPI、SQLAlchemy async、gRPC(已生成 stub)、Plan 5a 的 `ObjectStore`/`Skill`/`AgentSkillEnableRepository`、pytest + testcontainers。

**与 spec 的偏差(有意,v1):** spec §12.4 写 `location=/skills/<name>/`(用户级共享、缓存)。本计划用**每会话 `.skills/`**(相对 `work_subdir`),因为:(1) 沙箱工具只允许访问 `work_subdir`;(2) 同用户不同 agent 共用一个沙箱,用户级共享目录会让并发会话互相覆盖技能集。每回合重铺即天然失效;用户级共享 + 跨会话缓存留作后续优化。

---

## 测试约定(每个任务都遵守)

- **backend 测试必须** `TESTCONTAINERS_RYUK_DISABLED=true` + `--timeout=120`,且**用 `timeout` 包住**避免 gRPC e2e teardown 卡死整进程:
  - 非 e2e 快跑:`cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true timeout -k 5 220 uv run pytest -q --timeout=60 -p no:cacheprovider --ignore=tests/test_inprocess_provisioner.py --ignore=tests/test_per_user_routing_e2e.py --ignore=tests/test_turn_e2e.py --ignore=tests/test_turn_stream_e2e.py --ignore=tests/test_turn_endpoint.py --ignore=tests/test_turn_stream_endpoint.py --ignore=tests/test_sse.py --ignore=tests/test_skill_turn_e2e.py`
  - e2e 单跑:`cd .../services/backend && TESTCONTAINERS_RYUK_DISABLED=true timeout -k 5 240 uv run pytest -q --timeout=60 -p no:cacheprovider tests/test_turn_e2e.py tests/test_turn_stream_e2e.py tests/test_turn_endpoint.py tests/test_turn_stream_endpoint.py tests/test_sse.py tests/test_per_user_routing_e2e.py tests/test_inprocess_provisioner.py tests/test_skill_turn_e2e.py`
  - **绝不**把测试丢后台裸跑(后台命令不受 timeout 约束 → 会无限挂)。
- worker/common/sandbox 套件无 Docker:`cd <svc> && uv run pytest -q --timeout=60`。
- 每条命令显式 `cd` 到对应 service 目录(cwd 跨命令保持;从仓库根跑 pytest 会收集整个 monorepo 而报错)。

## 文件结构

**新建:**
- `services/backend/src/agent_cloud_backend/skills/materialize.py` — `skill_location` + `materialize_enabled_skills`
- `services/backend/tests/test_skill_materialize.py`
- `services/backend/tests/test_skill_turn_e2e.py`
- `services/worker/tests/test_tool_filtering.py`

**修改:**
- `services/worker/src/agent_cloud_worker/sandbox_executor.py` — `filtered_tool_specs` + 构造接受 `enabled_tools`
- `services/worker/src/agent_cloud_worker/server.py` — 把 `request.agent.enabled_tools` 传给 executor(RunTurn + RunTurnStream 两处)
- `services/backend/src/agent_cloud_backend/turn/assemble.py` — `build_run_turn_request` 增 `enabled_skills` 参数并填充 proto `skills`
- `services/backend/tests/test_assemble.py` — 新增 skills 填充用例
- `services/backend/src/agent_cloud_backend/api/turn.py` — 两个端点:加 `get_object_store` 依赖、查已启用 skill、物化、传给 assemble

---

## Task 1: worker 按 enabled_tools 过滤工具

**Files:**
- Modify: `services/worker/src/agent_cloud_worker/sandbox_executor.py`
- Modify: `services/worker/src/agent_cloud_worker/server.py`
- Test: `services/worker/tests/test_tool_filtering.py`

- [ ] **Step 1: 写失败测试**

Create `services/worker/tests/test_tool_filtering.py`:

```python
from agent_cloud_worker.sandbox_executor import filtered_tool_specs


def test_empty_enabled_tools_exposes_all():
    assert {s.name for s in filtered_tool_specs([])} == {"bash", "write_file", "read_file"}


def test_filters_to_enabled_subset():
    assert [s.name for s in filtered_tool_specs(["read_file"])] == ["read_file"]


def test_unknown_enabled_tool_ignored():
    assert {s.name for s in filtered_tool_specs(["read_file", "nope"])} == {"read_file"}


def test_order_follows_builtin_not_request():
    # 过滤保持内置顺序,稳定可预期
    names = [s.name for s in filtered_tool_specs(["read_file", "bash"])]
    assert names == ["bash", "read_file"]
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_tool_filtering.py -q --timeout=60
```
Expected: FAIL（`filtered_tool_specs` 不存在）。

- [ ] **Step 3: 实现过滤**

把 `sandbox_executor.py` 改为(加 `filtered_tool_specs` 模块函数,构造接受 `enabled_tools`,`specs()` 调用过滤):

```python
from __future__ import annotations

import json

import grpc
from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc
from agent_cloud_common import ToolCall, ToolResult, ToolSpec, builtin_tool_specs


def filtered_tool_specs(enabled_tools: list[str]) -> list[ToolSpec]:
    """按 enabled_tools 收窄内置工具集;空列表=全部(兼容未配置 enabled_tools 的 agent)。
    保持内置顺序,未知名忽略。"""
    specs = builtin_tool_specs()
    if not enabled_tools:
        return specs
    allowed = set(enabled_tools)
    return [s for s in specs if s.name in allowed]


class SandboxToolExecutor:
    """ToolExecutor 实现:把工具调用通过 gRPC 下发给沙箱服务执行。

    这是 worker→sandbox 信任边界的客户端侧:只传 工具名 + 参数 + 工作目录,
    不传 LLM Key。``enabled_tools`` 决定暴露给 LLM 的工具子集(per-agent)。
    """

    def __init__(
        self, channel: grpc.aio.Channel, work_subdir: str, enabled_tools: list[str] | None = None
    ) -> None:
        self._stub = sandbox_pb2_grpc.SandboxStub(channel)
        self._work_subdir = work_subdir
        self._enabled_tools = list(enabled_tools or [])

    def specs(self) -> list[ToolSpec]:
        return filtered_tool_specs(self._enabled_tools)

    async def execute(self, call: ToolCall) -> ToolResult:
        try:
            resp = await self._stub.ExecTool(
                sandbox_pb2.ExecToolRequest(
                    call_id=call.id,
                    tool_name=call.name,
                    arguments_json=json.dumps(call.arguments),
                    work_subdir=self._work_subdir,
                )
            )
        except grpc.aio.AioRpcError as exc:
            return ToolResult(
                call_id=call.id,
                content=f"sandbox RPC failed: {exc.code().name}",
                is_error=True,
            )
        return ToolResult(call_id=call.id, content=resp.content, is_error=resp.is_error)
```

- [ ] **Step 4: 在 server.py 把 enabled_tools 传给 executor(两处)**

在 `server.py` 的 `RunTurn` 与 `RunTurnStream` 里,把
```python
            executor = SandboxToolExecutor(channel, request.work_subdir)
```
改为
```python
            executor = SandboxToolExecutor(
                channel, request.work_subdir, list(request.agent.enabled_tools)
            )
```
(两处都改。)

- [ ] **Step 5: 跑测试确认通过 + worker 全量回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest -q --timeout=60
```
Expected: 全绿（含 test_tool_filtering 4 项;现有 worker 测试不受影响——它们的 agent 多无 enabled_tools,空=全部）。

- [ ] **Step 6: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/worker/src/agent_cloud_worker/sandbox_executor.py services/worker/src/agent_cloud_worker/server.py services/worker/tests/test_tool_filtering.py && git commit -m "feat(worker): filter exposed tools by agent.enabled_tools"
```

---

## Task 2: skill 物化器(对象存储 → 沙箱 work_subdir/.skills/)

**Files:**
- Create: `services/backend/src/agent_cloud_backend/skills/materialize.py`
- Test: `services/backend/tests/test_skill_materialize.py`

- [ ] **Step 1: 写失败测试**

Create `services/backend/tests/test_skill_materialize.py`:

```python
import uuid

from agent_cloud_backend.models.skill import Skill
from agent_cloud_backend.skills.materialize import (
    SKILLS_SUBDIR,
    materialize_enabled_skills,
    skill_location,
)
from agent_cloud_backend.skills.store import LocalObjectStore


def _store_with_skill(tmp_path, uid, name="example"):
    store = LocalObjectStore(tmp_path / "obj")
    src = tmp_path / f"src-{name}"
    (src / "scripts").mkdir(parents=True)
    (src / "SKILL.md").write_text(f"# {name}")
    (src / "scripts" / "go.sh").write_text("echo hi")
    ref = f"users/{uid}/skills/{name}"
    store.put_dir(ref, src)
    return store, ref


def _skill(uid, name, ref):
    return Skill(
        user_id=uid, name=name, description="d", source="registry",
        version="1.0.0", requires={}, package_ref=ref,
    )


def test_skill_location():
    assert skill_location("foo") == ".skills/foo/SKILL.md"


def test_materialize_copies_into_work_subdir(tmp_path):
    uid = uuid.uuid4()
    store, ref = _store_with_skill(tmp_path, uid, "example")
    materialize_enabled_skills(
        base_root=tmp_path / "boxes", user_id=uid, work_subdir="sessions/s1",
        skills=[_skill(uid, "example", ref)], store=store,
    )
    base = tmp_path / "boxes" / str(uid) / "sessions/s1" / SKILLS_SUBDIR / "example"
    assert (base / "SKILL.md").read_text() == "# example"
    assert (base / "scripts" / "go.sh").read_text() == "echo hi"


def test_materialize_removes_stale_skills(tmp_path):
    uid = uuid.uuid4()
    store, ref = _store_with_skill(tmp_path, uid, "keep")
    wd = "sessions/s1"
    stale = tmp_path / "boxes" / str(uid) / wd / SKILLS_SUBDIR / "stale"
    stale.mkdir(parents=True)
    (stale / "SKILL.md").write_text("old")
    materialize_enabled_skills(
        base_root=tmp_path / "boxes", user_id=uid, work_subdir=wd,
        skills=[_skill(uid, "keep", ref)], store=store,
    )
    root = tmp_path / "boxes" / str(uid) / wd / SKILLS_SUBDIR
    assert (root / "keep" / "SKILL.md").exists()
    assert not (root / "stale").exists()


def test_materialize_empty_clears_skills_dir(tmp_path):
    uid = uuid.uuid4()
    wd = "sessions/s1"
    root = tmp_path / "boxes" / str(uid) / wd / SKILLS_SUBDIR
    (root / "x").mkdir(parents=True)
    materialize_enabled_skills(
        base_root=tmp_path / "boxes", user_id=uid, work_subdir=wd, skills=[],
        store=LocalObjectStore(tmp_path / "obj"),
    )
    assert not root.exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true timeout -k 5 60 uv run pytest tests/test_skill_materialize.py -q --timeout=60
```
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 写实现**

Create `services/backend/src/agent_cloud_backend/skills/materialize.py`:

```python
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from agent_cloud_backend.models.skill import Skill
from agent_cloud_backend.skills.store import ObjectStore

SKILLS_SUBDIR = ".skills"


def skill_location(name: str) -> str:
    """回合内 agent 读取 SKILL.md 的路径(相对 work_subdir,落在沙箱工具容器内)。"""
    return f"{SKILLS_SUBDIR}/{name}/SKILL.md"


def materialize_enabled_skills(
    *,
    base_root: Path,
    user_id: uuid.UUID,
    work_subdir: str,
    skills: list[Skill],
    store: ObjectStore,
) -> None:
    """把已启用 skill 从对象存储铺到 <base_root>/<user_id>/<work_subdir>/.skills/<name>/。

    先整体清空 .skills/ 再逐个铺:这样停用/卸载的 skill 不会在本会话残留,
    每回合的 .skills/ 恰好等于当前启用集(天然失效,无需缓存)。同会话回合被会话
    锁串行化;不同会话(含同用户不同 agent)用不同 work_subdir,互不干扰。
    """
    skills_root = Path(base_root) / str(user_id) / work_subdir / SKILLS_SUBDIR
    if skills_root.exists():
        shutil.rmtree(skills_root)
    for skill in skills:
        store.get_dir(skill.package_ref, skills_root / skill.name)
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true timeout -k 5 60 uv run pytest tests/test_skill_materialize.py -q --timeout=60
```
Expected: 5 passed。

- [ ] **Step 5: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/src/agent_cloud_backend/skills/materialize.py services/backend/tests/test_skill_materialize.py && git commit -m "feat(backend): materialize enabled skills into per-session sandbox .skills/"
```

---

## Task 3: assemble 填充 run_turn 的 skills 元数据

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/turn/assemble.py`
- Test: `services/backend/tests/test_assemble.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_assemble.py` 顶部 import 区加:

```python
from agent_cloud_backend.models.skill import Skill
from agent_cloud_backend.repositories.skill import SkillRepository
```

并在文件末尾追加:

```python
async def test_build_request_includes_enabled_skills(session):
    user = await UserRepository(session).create(User(email="sk@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, name="c", model="m", provider="p")
    )
    await session.flush()
    s = await SessionRepository(session).create_for(user.id, agent.id, None)
    await session.flush()
    skill = await SkillRepository(session).create(
        Skill(
            user_id=user.id, name="greet", description="say hi", source="registry",
            version="1.0.0", requires={}, package_ref=f"users/{user.id}/skills/greet",
        )
    )
    await session.commit()

    req = await build_run_turn_request(
        session, s, sandbox_endpoint="x", user_message="hi",
        exclude_message_id=None, enabled_skills=[skill],
    )
    assert len(req.skills) == 1
    assert req.skills[0].name == "greet"
    assert req.skills[0].description == "say hi"
    assert req.skills[0].location == ".skills/greet/SKILL.md"


async def test_build_request_skills_default_empty(session):
    user = await UserRepository(session).create(User(email="sk2@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, name="c", model="m", provider="p")
    )
    await session.flush()
    s = await SessionRepository(session).create_for(user.id, agent.id, None)
    await session.commit()
    req = await build_run_turn_request(
        session, s, sandbox_endpoint="x", user_message="hi", exclude_message_id=None
    )
    assert list(req.skills) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true timeout -k 5 90 uv run pytest tests/test_assemble.py -q --timeout=60
```
Expected: FAIL（`build_run_turn_request` 还没有 `enabled_skills` 参数）。

- [ ] **Step 3: 实现 assemble 填充**

在 `assemble.py` 顶部 import 区加:
```python
from agent_cloud_backend.models.skill import Skill
from agent_cloud_backend.skills.materialize import skill_location
```

把函数签名加上 `enabled_skills` 参数(默认 None),并把 proto 的 `skills=[]  # Plan 5` 替换为真正填充。完整改动:签名行
```python
    exclude_message_id: uuid.UUID | None,
) -> worker_pb2.RunTurnRequest:
```
改为
```python
    exclude_message_id: uuid.UUID | None,
    enabled_skills: list[Skill] | None = None,
) -> worker_pb2.RunTurnRequest:
```
并把
```python
        skills=[],  # Plan 5
```
改为
```python
        skills=[
            worker_pb2.Skill(
                name=sk.name, description=sk.description, location=skill_location(sk.name)
            )
            for sk in (enabled_skills or [])
        ],
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true timeout -k 5 90 uv run pytest tests/test_assemble.py -q --timeout=60
```
Expected: 全绿（原 2 + 新 2 = 4）。

- [ ] **Step 5: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/src/agent_cloud_backend/turn/assemble.py services/backend/tests/test_assemble.py && git commit -m "feat(backend): populate run_turn skills metadata from enabled skills"
```

---

## Task 4: 回合端点接线(查已启用 skill → 物化 → 传 assemble)

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/api/turn.py`
- (验证)`services/backend/tests/test_turn_endpoint.py`、`test_turn_stream_endpoint.py`

- [ ] **Step 1: 加 import**

在 `api/turn.py` import 区加:
```python
from pathlib import Path

from agent_cloud_backend.repositories.skill import AgentSkillEnableRepository
from agent_cloud_backend.skills.deps import get_object_store
from agent_cloud_backend.skills.materialize import materialize_enabled_skills
from agent_cloud_backend.skills.store import ObjectStore
```

- [ ] **Step 2: run_turn_endpoint 接线**

在 `run_turn_endpoint` 的签名加依赖参数(放 `manager` 之后):
```python
    store: ObjectStore = Depends(get_object_store),
```
把第 3 步组装那段:
```python
        # 3. 组装 + 调 worker
        sandbox_endpoint = await manager.get_endpoint_for_user(s.user_id)
        request = await build_run_turn_request(
            db,
            s,
            sandbox_endpoint=sandbox_endpoint,
            user_message=body.content,
            exclude_message_id=user_msg.id,
        )
```
替换为:
```python
        # 3. 组装 + 物化已启用 skill + 调 worker
        sandbox_endpoint = await manager.get_endpoint_for_user(s.user_id)
        enabled_skills = await AgentSkillEnableRepository(db).list_enabled_for_agent(
            s.agent_config_id
        )
        materialize_enabled_skills(
            base_root=Path(settings.sandbox_base_root),
            user_id=s.user_id,
            work_subdir=s.work_subdir,
            skills=enabled_skills,
            store=store,
        )
        request = await build_run_turn_request(
            db,
            s,
            sandbox_endpoint=sandbox_endpoint,
            user_message=body.content,
            exclude_message_id=user_msg.id,
            enabled_skills=enabled_skills,
        )
```

- [ ] **Step 3: stream_turn_endpoint 接线**

在 `stream_turn_endpoint` 的签名加依赖参数(放 `manager` 之后):
```python
    store: ObjectStore = Depends(get_object_store),
```
把其中:
```python
        sandbox_endpoint = await manager.get_endpoint_for_user(s.user_id)
        request = await build_run_turn_request(
            db,
            s,
            sandbox_endpoint=sandbox_endpoint,
            user_message=body.content,
            exclude_message_id=user_msg.id,
        )
```
替换为:
```python
        sandbox_endpoint = await manager.get_endpoint_for_user(s.user_id)
        enabled_skills = await AgentSkillEnableRepository(db).list_enabled_for_agent(
            s.agent_config_id
        )
        materialize_enabled_skills(
            base_root=Path(settings.sandbox_base_root),
            user_id=s.user_id,
            work_subdir=s.work_subdir,
            skills=enabled_skills,
            store=store,
        )
        request = await build_run_turn_request(
            db,
            s,
            sandbox_endpoint=sandbox_endpoint,
            user_message=body.content,
            exclude_message_id=user_msg.id,
            enabled_skills=enabled_skills,
        )
```

- [ ] **Step 4: 跑现有端点测试确认未回归**

`conftest.py` 的 `client`/`client_noraise` 已 override `get_object_store`(Plan 5a),无 skill 启用时 `materialize_enabled_skills` 是 no-op(空集 → 清空不存在的 .skills → 啥也不铺)。

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true timeout -k 5 240 uv run pytest tests/test_turn_endpoint.py tests/test_turn_stream_endpoint.py tests/test_turn_e2e.py tests/test_turn_stream_e2e.py -q --timeout=60 -p no:cacheprovider
```
Expected: 全绿。**若**某测试自建 app(未用 conftest 的 `client`),报 `get_object_store` 相关错,则给那个 app 加 `app.dependency_overrides[get_object_store] = lambda: LocalObjectStore(tmp_path / "obj")`(参照 Task 5 的 stack fixture)。

- [ ] **Step 5: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/src/agent_cloud_backend/api/turn.py && git commit -m "feat(backend): materialize + inject enabled skills on each turn"
```

---

## Task 5: 端到端(install → enable → 回合中 agent 读到物化的 SKILL.md)

**Files:**
- Create: `services/backend/tests/test_skill_turn_e2e.py`

- [ ] **Step 1: 写测试**

Create `services/backend/tests/test_skill_turn_e2e.py`:

```python
import pytest_asyncio
from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.main import create_app
from agent_cloud_backend.sandbox.deps import get_sandbox_manager
from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner
from agent_cloud_backend.sandbox.manager import SandboxManager
from agent_cloud_backend.skills.deps import get_object_store
from agent_cloud_backend.skills.store import LocalObjectStore
from agent_cloud_common import CompletionResult, Message, Role, ToolCall, Usage
from agent_cloud_worker.provider import FakeProvider
from agent_cloud_worker.server import create_server as create_worker_server
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker


@pytest_asyncio.fixture
async def skill_stack(engine, tmp_path):
    # FakeProvider:第一轮让 agent 读已物化的 SKILL.md,第二轮收尾。
    provider = FakeProvider(
        [
            CompletionResult(
                message=Message(
                    role=Role.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="read_file",
                            arguments={"path": ".skills/example-greeting/SKILL.md"},
                        )
                    ],
                ),
                usage=Usage(input_tokens=1, output_tokens=1),
            ),
            CompletionResult(
                message=Message(role=Role.ASSISTANT, text="read it"),
                usage=Usage(input_tokens=1, output_tokens=1),
            ),
        ]
    )
    worker_server, wport = await create_worker_server(provider_factory=lambda *a: provider, port=0)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_session():
        async with maker() as sdb:
            yield sdb

    # 关键:物化器用 settings.sandbox_base_root,provisioner 用同一 tmp_path,二者必须一致
    def _override_settings():
        return Settings(worker_endpoint=f"localhost:{wport}", sandbox_base_root=str(tmp_path))

    manager = SandboxManager(
        provisioner=InProcessProvisioner(base_root=tmp_path), sessionmaker=maker
    )
    store = LocalObjectStore(tmp_path / "obj")

    app = create_app()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_sandbox_manager] = lambda: manager
    app.dependency_overrides[get_object_store] = lambda: store
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, tmp_path
    await worker_server.stop(None)


async def test_enabled_skill_is_materialized_and_readable(skill_stack):
    client, base = skill_stack
    uid = (await client.post("/users", json={"email": "ske2e@example.com"})).json()["id"]
    aid = (
        await client.post(
            "/agent-configs",
            json={"user_id": uid, "name": "coder", "model": "m", "provider": "fake"},
        )
    ).json()["id"]
    # 从内置 registry 安装 + 给该 agent 启用
    skill_id = (
        await client.post("/skills/install", json={"user_id": uid, "name": "example-greeting"})
    ).json()["id"]
    r = await client.put(f"/agent-configs/{aid}/skills", json={"skill_ids": [skill_id]})
    assert r.status_code == 200, r.text

    sid = (await client.post("/sessions", json={"user_id": uid, "agent_config_id": aid})).json()[
        "id"
    ]
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "use the skill"})
    assert r.status_code == 200, r.text
    assert r.json()["stop_reason"] == "end_turn"

    # 1) skill 物化到了该会话沙箱目录
    md = base / str(uid) / f"sessions/{sid}" / ".skills" / "example-greeting" / "SKILL.md"
    assert md.is_file()
    assert "example-greeting" in md.read_text()

    # 2) agent 确实读到了它(tool 消息回填了 SKILL.md 内容)
    listed = (await client.get(f"/sessions/{sid}/messages")).json()
    assert [m["role"] for m in listed] == ["user", "assistant", "tool", "assistant"]
    tool_msg = listed[2]
    results = tool_msg["content"]["tool_results"]
    assert results and "example-greeting" in results[0]["content"]
    assert results[0]["is_error"] is False


async def test_disabled_skill_not_materialized(skill_stack):
    # 装了但不给 agent 启用 → 不应物化到沙箱
    client, base = skill_stack
    uid = (await client.post("/users", json={"email": "skoff@example.com"})).json()["id"]
    aid = (
        await client.post(
            "/agent-configs",
            json={"user_id": uid, "name": "c", "model": "m", "provider": "fake"},
        )
    ).json()["id"]
    await client.post("/skills/install", json={"user_id": uid, "name": "example-greeting"})
    # 不调用 PUT /skills(不启用)
    sid = (await client.post("/sessions", json={"user_id": uid, "agent_config_id": aid})).json()[
        "id"
    ]
    # FakeProvider 第一轮会尝试 read_file,读不到 → is_error;第二轮收尾。回合仍 200。
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "x"})
    assert r.status_code == 200, r.text
    assert not (base / str(uid) / f"sessions/{sid}" / ".skills").exists()
```

- [ ] **Step 2: 跑测试确认通过**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true timeout -k 5 180 uv run pytest tests/test_skill_turn_e2e.py -q --timeout=90 -p no:cacheprovider
```
Expected: 2 passed（若卡在 teardown,`timeout` 会兜底;`[100%]`/`2 passed` 出现即成功)。

- [ ] **Step 3: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/tests/test_skill_turn_e2e.py && git commit -m "test(backend): e2e skill install->enable->materialize->agent reads SKILL.md"
```

---

## Task 6: 收尾(分段回归 + lint)

**Files:** 无(仅验证)

- [ ] **Step 1: backend 分段回归(非 e2e + e2e)**

Run(两条,见顶部「测试约定」的完整 ignore / 文件清单):
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true timeout -k 5 220 uv run pytest -q --timeout=60 -p no:cacheprovider --ignore=tests/test_inprocess_provisioner.py --ignore=tests/test_per_user_routing_e2e.py --ignore=tests/test_turn_e2e.py --ignore=tests/test_turn_stream_e2e.py --ignore=tests/test_turn_endpoint.py --ignore=tests/test_turn_stream_endpoint.py --ignore=tests/test_sse.py --ignore=tests/test_skill_turn_e2e.py
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true timeout -k 5 300 uv run pytest -q --timeout=90 -p no:cacheprovider tests/test_inprocess_provisioner.py tests/test_per_user_routing_e2e.py tests/test_turn_e2e.py tests/test_turn_stream_e2e.py tests/test_turn_endpoint.py tests/test_turn_stream_endpoint.py tests/test_sse.py tests/test_skill_turn_e2e.py
```
Expected: 两段都全绿。

- [ ] **Step 2: worker / common / sandbox 回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest -q --timeout=60
cd /Users/wuhaowen/src/llm-agent/agent-cloud/packages/common && uv run pytest -q --timeout=60
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run pytest -q --timeout=60
```
Expected: 全绿。

- [ ] **Step 3: ruff**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && uv run ruff check services/backend services/worker
```
Expected: `All checks passed!`（如有问题 `--fix` 后复跑;注意 B904/E501 不一定可自动修)。

- [ ] **Step 4: 最终 commit(若 ruff 有改动)**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add -A services/backend services/worker && git commit -m "chore: ruff clean for skill turn integration"
```

---

## Self-Review(对照 spec §12.4 + 用户提出的 per-agent 关切)

- **§12.4-1 物化已启用 skill 进沙箱**:Task 2 `materialize_enabled_skills`,Task 4 在回合开始调用。✔(用每会话 `.skills/`,见顶部「偏差」)
- **§12.4-2 注入 `<available_skills>` 元数据**:worker `context.build_system_prompt` 已实现;Task 3 让后端填 `RunTurnRequest.skills`(name/description/location),worker `server.py` 已把 `request.skills` 喂给它。✔
- **§12.4-3/4 agent 读 SKILL.md 并跑脚本**:`location=.skills/<name>/SKILL.md` 落在 `work_subdir` 容器内,Task 5 e2e 证明 `read_file` 能读到。✔
- **per-agent 隔离(用户关切)**:skill 按 `list_enabled_for_agent(session.agent_config_id)` 取、物化进每会话 `work_subdir/.skills/`;tool 按 `agent.enabled_tools` 过滤。同用户不同 agent 的并发会话各用各 work_subdir,互不覆盖。✔
- **install/uninstall 失效**:每回合先清空再重铺 `.skills/` = 天然失效(无跨会话缓存,见偏差)。✔
- **留作后续**:用户级共享 `/skills/` + 跨会话缓存;sandbox 侧对未启用工具的二次拒绝(目前只在 worker 侧不暴露给 LLM,足够 v1)。

类型/签名一致性:`filtered_tool_specs(enabled_tools)`、`SandboxToolExecutor(channel, work_subdir, enabled_tools=None)`、`skill_location(name)`、`materialize_enabled_skills(*, base_root, user_id, work_subdir, skills, store)`、`build_run_turn_request(..., enabled_skills=None)`、`AgentSkillEnableRepository.list_enabled_for_agent`、`get_object_store` —— 跨任务引用一致。✔
