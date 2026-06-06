# Plan 4b: 后端每用户 sandbox 路由 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 turn 端点(一元 + SSE)从静态 `sandbox_endpoint` 切换为按用户路由:经 `SandboxManager.get_endpoint_for_user(user_id)` 取/起该用户的 sandbox。完成"每用户 sandbox"闭环。

**Architecture:** 新增 `get_sandbox_manager` 依赖(进程级单例:`InProcessProvisioner` + 全局 sessionmaker)。两个 turn 端点在前置步骤里 `sandbox_endpoint = await manager.get_endpoint_for_user(session.user_id)`,传入 `build_run_turn_request`。配置去掉静态 `sandbox_endpoint`,加 `sandbox_base_root`。测试通过 `app.dependency_overrides[get_sandbox_manager]` 注入测试用 manager(单测用 `FakeProvisioner` 免起真沙箱;e2e 用 `InProcessProvisioner(tmp)`)。

**Tech Stack:** FastAPI 依赖注入、SQLAlchemy async、grpcio、pytest + testcontainers。

参考:spec §8(step 3 "确保用户 sandbox 在线并传 endpoint")、§5.1、§9;已合并:4a(`SandboxManager`/`InProcessProvisioner`/`SandboxRegistry`)、2d(一元 turn)、3c(SSE turn)。

## 范围

**做**:`get_sandbox_manager` 依赖 + 配置改动;两个 turn 端点按用户路由;更新现有 turn 单测 + e2e;新增跨用户隔离 e2e。

**不做(后续小计划)**:M1 死端点存活检测/健康检查/heartbeat(仅跨后端重启才需要;4a 已留 `# NOTE(4b)`,顺延为"sandbox 健康"小计划);reaper 周期调度(部署期 cron 调 `reap_idle`);真实 Docker provisioner。

> **必须原子**:端点改路由会让旧的 turn e2e(2d/3c 用静态 `sandbox_endpoint`)失效,故路由改动 + 全部测试更新在本计划内一起完成,保证套件常绿。

## File Structure

```
services/backend/src/agent_cloud_backend/
  config.py                 # -sandbox_endpoint, +sandbox_base_root
  sandbox/deps.py           # get_sandbox_manager(进程单例)
  api/turn.py               # 两个端点改用 manager 路由
services/backend/tests/
  test_turn_endpoint.py     # 更新:override get_sandbox_manager(FakeProvisioner manager)
  test_turn_stream_endpoint.py  # 同上
  test_turn_e2e.py          # 更新:manager + InProcessProvisioner(tmp),去掉手起 sandbox
  test_turn_stream_e2e.py   # 同上
  test_per_user_routing_e2e.py  # 新增:两用户 -> 各自 sandbox,文件隔离
```

---

### Task 0: get_sandbox_manager 依赖 + 配置 + 端点路由

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/config.py`, `services/backend/src/agent_cloud_backend/api/turn.py`
- Create: `services/backend/src/agent_cloud_backend/sandbox/deps.py`

- [ ] **Step 1: 配置改动**

Edit `services/backend/src/agent_cloud_backend/config.py` `Settings`:
- 删除 `sandbox_endpoint` 字段。
- 加 `sandbox_base_root: str = "/tmp/agent-cloud-sandboxes"`。
(保留 `worker_endpoint`。)

- [ ] **Step 2: 写 manager 依赖**

Create `services/backend/src/agent_cloud_backend/sandbox/deps.py`:
```python
from __future__ import annotations

from pathlib import Path

from agent_cloud_backend.config import get_settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner
from agent_cloud_backend.sandbox.manager import SandboxManager

_manager: SandboxManager | None = None


def get_sandbox_manager() -> SandboxManager:
    """进程级单例 SandboxManager(provisioner 持有进程内沙箱句柄,故必须单例)。
    测试通过 app.dependency_overrides[get_sandbox_manager] 注入自己的 manager。"""
    global _manager
    if _manager is None:
        settings = get_settings()
        provisioner = InProcessProvisioner(base_root=Path(settings.sandbox_base_root))
        _manager = SandboxManager(provisioner=provisioner, sessionmaker=get_sessionmaker())
    return _manager
```

- [ ] **Step 3: 端点改路由**

Edit `services/backend/src/agent_cloud_backend/api/turn.py`:
- Add import: `from agent_cloud_backend.sandbox.deps import get_sandbox_manager` and `from agent_cloud_backend.sandbox.manager import SandboxManager`.
- In BOTH `run_turn_endpoint` (unary) and `stream_turn_endpoint` (SSE): add a dependency param `manager: SandboxManager = Depends(get_sandbox_manager)`, and in the pre-flight (inside the existing `try` that builds the request), replace `sandbox_endpoint=settings.sandbox_endpoint` with a resolved endpoint:
```python
        sandbox_endpoint = await manager.get_endpoint_for_user(s.user_id)
        request = await build_run_turn_request(
            db, s, sandbox_endpoint=sandbox_endpoint,
            user_message=body.content, exclude_message_id=user_msg.id,
        )
```
(The `await manager.get_endpoint_for_user(...)` goes inside the same pre-flight `try/except` that already releases the lock on failure — so a provisioning failure releases the lock and surfaces as 5xx.)

- [ ] **Step 4: 运行(预期部分失败 —— 旧测试待 Task 1/2 更新)**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest -q 2>&1 | tail -15`
Expected: the turn endpoint/e2e tests now FAIL (they don't provide a `get_sandbox_manager` override yet / still set `sandbox_endpoint`). This is expected — Tasks 1-2 fix them. Confirm the FAILURES are confined to `test_turn_endpoint.py`, `test_turn_stream_endpoint.py`, `test_turn_e2e.py`, `test_turn_stream_e2e.py` (other suites stay green).

- [ ] **Step 5: 提交**

```bash
git add services/backend/src/agent_cloud_backend/config.py services/backend/src/agent_cloud_backend/sandbox/deps.py services/backend/src/agent_cloud_backend/api/turn.py
git commit -m "feat(backend): route turns to per-user sandbox via SandboxManager"
```

---

### Task 1: 更新 turn 单元测试(override get_sandbox_manager)

**Files:**
- Modify: `services/backend/tests/test_turn_endpoint.py`, `services/backend/tests/test_turn_stream_endpoint.py`

> 单测 fake 掉 worker,sandbox_endpoint 无所谓 —— 用 `FakeProvisioner` 的 manager 避免起真沙箱(快)。

- [ ] **Step 1: 加一个共享 override helper(放 conftest.py)**

Append to `services/backend/tests/conftest.py`:
```python
import uuid as _uuid

from agent_cloud_backend.sandbox.deps import get_sandbox_manager
from agent_cloud_backend.sandbox.manager import SandboxManager


class _FakeProvisioner:
    async def spawn(self, user_id):
        return _uuid.uuid4(), f"fake-sandbox:{user_id}"

    async def stop(self, sandbox_id):
        return None


def override_sandbox_manager_fake(app, engine):
    """让端点用一个 FakeProvisioner 的 manager(不起真沙箱)。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False)
    manager = SandboxManager(provisioner=_FakeProvisioner(), sessionmaker=maker)
    app.dependency_overrides[get_sandbox_manager] = lambda: manager
    return manager
```

- [ ] **Step 2: 让 `client` fixture 也装上 fake manager**

In `services/backend/tests/conftest.py`, in the `client` fixture (the one that builds the app + overrides `get_session`), after creating `app` and before yielding, add:
```python
    override_sandbox_manager_fake(app, engine)
```
(`engine` is already a fixture; `client` already depends on it. If `client` doesn't currently take `engine`, add it to its parameters.)

- [ ] **Step 3: 运行单测,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_turn_endpoint.py tests/test_turn_stream_endpoint.py -q`
Expected: PASS (the fake manager returns a fake endpoint; the faked worker ignores it; lock/persist/SSE assertions unchanged). If any test referenced `sandbox_endpoint`, none should — they monkeypatch the worker, not the sandbox.

- [ ] **Step 4: 提交**

```bash
git add services/backend/tests/conftest.py services/backend/tests/test_turn_endpoint.py services/backend/tests/test_turn_stream_endpoint.py
git commit -m "test(backend): override sandbox manager with fake provisioner in turn unit tests"
```

---

### Task 2: 更新 turn e2e(manager + InProcessProvisioner)

**Files:**
- Modify: `services/backend/tests/test_turn_e2e.py`, `services/backend/tests/test_turn_stream_e2e.py`

> e2e 用真 worker + 真沙箱,但沙箱由 manager 的 `InProcessProvisioner` 起(不再手起)。文件落在 `tmp/{user_id}/sessions/{sid}/`。

- [ ] **Step 1: 改 test_turn_e2e.py 的 `stack` fixture**

In `services/backend/tests/test_turn_e2e.py`:
- 删除手起 sandbox 的两行(`create_sandbox_server(...)` 与对应的 `await sandbox_server.stop(None)`)和 `import ... create_server as create_sandbox_server`。
- `get_settings` override 去掉 `sandbox_endpoint=...`(只留 `worker_endpoint=f"localhost:{wport}"`)。
- 注入 manager override:
```python
    from agent_cloud_backend.sandbox.deps import get_sandbox_manager
    from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner
    from agent_cloud_backend.sandbox.manager import SandboxManager
    maker = async_sessionmaker(engine, expire_on_commit=False)
    manager = SandboxManager(
        provisioner=InProcessProvisioner(base_root=tmp_path), sessionmaker=maker)
    app.dependency_overrides[get_sandbox_manager] = lambda: manager
```
- 文件断言改为按用户目录:`assert (base / str(uid) / f"sessions/{sid}" / "hi.txt").read_text() == "yo"` — 即 e2e 测试需要拿到 `uid`(create user 的返回 id),并断言文件在 `tmp_path/{uid}/sessions/{sid}/`。
- teardown 里只 `await worker_server.stop(None)`(沙箱由 manager 的 provisioner 起;测试结束后进程内服务器随 tmp 清理;可选地 `await manager.reap_idle()` 后再停,但非必须)。

- [ ] **Step 2: 改 test_turn_stream_e2e.py 的 `stack` fixture**

同 Step 1 的改法(去掉手起 sandbox、去掉 `sandbox_endpoint` setting、注入 manager override);文件断言改为 `(base / str(uid) / f"sessions/{sid}" / "hi.txt")`。

- [ ] **Step 3: 运行 e2e,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_turn_e2e.py tests/test_turn_stream_e2e.py -v`
Expected: PASS(2 passed)。

- [ ] **Step 4: 提交**

```bash
git add services/backend/tests/test_turn_e2e.py services/backend/tests/test_turn_stream_e2e.py
git commit -m "test(backend): turn e2e routes via sandbox manager + InProcessProvisioner"
```

---

### Task 3: 跨用户隔离 e2e + 收尾

**Files:**
- Create: `services/backend/tests/test_per_user_routing_e2e.py`
- Modify: `services/backend/README.md`

- [ ] **Step 1: 写跨用户隔离 e2e**

Create `services/backend/tests/test_per_user_routing_e2e.py`:
```python
import json

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.main import create_app
from agent_cloud_backend.models.sandbox_registry import SandboxRegistry
from agent_cloud_backend.sandbox.deps import get_sandbox_manager
from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner
from agent_cloud_backend.sandbox.manager import SandboxManager
from agent_cloud_common import CompletionResult, Message, Role, ToolCall, Usage
from agent_cloud_worker.provider import FakeProvider
from agent_cloud_worker.server import create_server as create_worker_server


def _writer_provider(path, content):
    return FakeProvider([
        CompletionResult(message=Message(role=Role.ASSISTANT, tool_calls=[
            ToolCall(id="c1", name="write_file", arguments={"path": path, "content": content})]),
            usage=Usage(input_tokens=1, output_tokens=1)),
        CompletionResult(message=Message(role=Role.ASSISTANT, text="done"),
                         usage=Usage(input_tokens=1, output_tokens=1)),
    ])


@pytest_asyncio.fixture
async def stack(engine, tmp_path):
    # worker uses a per-request provider via the factory; here both turns write distinct content
    # by giving each its own provider is overkill — use one provider per turn through the factory queue.
    maker = async_sessionmaker(engine, expire_on_commit=False)
    providers = {}

    def factory(model, provider, key_ref):
        # provider name carries which script to use (test wires it via agent.provider)
        return providers[provider]

    worker_server, wport = await create_worker_server(provider_factory=factory, port=0)
    manager = SandboxManager(provisioner=InProcessProvisioner(base_root=tmp_path), sessionmaker=maker)

    async def _override_session():
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_settings] = lambda: Settings(worker_endpoint=f"localhost:{wport}")
    app.dependency_overrides[get_sandbox_manager] = lambda: manager
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, tmp_path, maker, providers
    await worker_server.stop(None)


async def _user_session(client, email, provider_name):
    uid = (await client.post("/users", json={"email": email})).json()["id"]
    aid = (await client.post("/agent-configs",
           json={"user_id": uid, "name": "c", "model": "m", "provider": provider_name})).json()["id"]
    sid = (await client.post("/sessions", json={"user_id": uid, "agent_config_id": aid})).json()["id"]
    return uid, sid


async def test_two_users_get_isolated_sandboxes(stack):
    client, base, maker, providers = stack
    providers["pa"] = _writer_provider("a.txt", "alpha")
    providers["pb"] = _writer_provider("b.txt", "beta")

    uid_a, sid_a = await _user_session(client, "a@e.com", "pa")
    uid_b, sid_b = await _user_session(client, "b@e.com", "pb")

    ra = await client.post(f"/sessions/{sid_a}/turn", json={"content": "write a"})
    rb = await client.post(f"/sessions/{sid_b}/turn", json={"content": "write b"})
    assert ra.status_code == 200 and rb.status_code == 200

    # each user's file is under its OWN per-user sandbox dir; not visible to the other
    assert (base / str(uid_a) / f"sessions/{sid_a}" / "a.txt").read_text() == "alpha"
    assert (base / str(uid_b) / f"sessions/{sid_b}" / "b.txt").read_text() == "beta"
    assert not (base / str(uid_a)).joinpath(f"sessions/{sid_b}", "b.txt").exists()

    # registry has one active sandbox per user
    async with maker() as db:
        rows = (await db.execute(
            select(SandboxRegistry).where(SandboxRegistry.status == "active"))).scalars().all()
    by_user = {r.user_id for r in rows}
    assert by_user == {__import__("uuid").UUID(uid_a), __import__("uuid").UUID(uid_b)}
```

- [ ] **Step 2: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_per_user_routing_e2e.py -v`
Expected: PASS(1 passed)。

- [ ] **Step 3: lint + README**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run ruff check --fix . && uv run ruff format .`

在 `services/backend/README.md` 的"Sandbox 管理"节后追加:
```markdown
- turn 端点(一元 + SSE)现按用户路由:`sandbox_endpoint = await SandboxManager.get_endpoint_for_user(user_id)`;不同用户进各自 sandbox(各自持久工作目录)。配置 `AGENT_CLOUD_SANDBOX_BASE_ROOT`(InProcessProvisioner 根目录)。死端点存活检测/健康检查为后续。
```

- [ ] **Step 4: 全回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/packages/common && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest -q
```
Expected:common 9;sandbox 23;worker 49;backend 68(67 + 跨用户 e2e 1;turn 单测/ e2e 数量不变,只是改了 wiring)。

- [ ] **Step 5: 提交**

```bash
git add services/backend/tests/test_per_user_routing_e2e.py services/backend/README.md
git commit -m "test(backend): per-user sandbox isolation e2e; document routing"
```

---

## Self-Review(写完后自检结果)

**Spec 覆盖(Plan 4b 范围)**:
- §8 step 3(确保用户 sandbox 在线并把 endpoint 传给 worker)→ 两端点 `await manager.get_endpoint_for_user(user_id)` 后传入 `RunTurnRequest.sandbox_endpoint`。✓
- §5.1 每用户 sandbox + §9 路由 → 跨用户 e2e 证明两用户进各自 sandbox、文件隔离、注册表每用户一条 active。✓
- 失败处理:`get_endpoint_for_user` 在前置 `try` 内,provisioning 失败 → 释放锁 + 5xx(复用 2d/3c 的前置 except)。✓
- 明确延后:M1 死端点存活/健康(跨重启才需要)、reaper 周期调度、真实 Docker provisioner。

**占位符扫描**:无 TBD;每步完整代码或确切命令/预期。Task 0 Step 4 显式预期"旧测试失败、Task 1/2 修复",非占位。

**原子性**:路由改动(Task 0)立即让旧 turn 测试红,Task 1(单测)+ Task 2(e2e)在同一计划内恢复绿;最终全套绿。

**类型/命名一致性**:`get_sandbox_manager()` 进程单例,测试 override;端点 `Depends(get_sandbox_manager)` + `await manager.get_endpoint_for_user(s.user_id)`;复用 4a 的 `SandboxManager(provisioner, sessionmaker)`/`InProcessProvisioner(base_root)`、2d 的 `build_run_turn_request(..., sandbox_endpoint=...)`/前置锁释放、3c 的 SSE 生成器(sandbox_endpoint 在前置解析后进 request);config 去 `sandbox_endpoint`、加 `sandbox_base_root`(e2e 的 get_settings override 同步去掉该字段)。
```
