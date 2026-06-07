# Docker 沙箱 Provisioner 实现计划(Part 2:reaper loop + 接线 + worker 重试 + dev_up + 集成测试)

> 接 `2026-06-07-plan-8-docker-sandbox-provisioner.md`。命令约定同 Part 1(backend 测试在 `services/backend` 下、`TESTCONTAINERS_RYUK_DISABLED=true`、绝对路径 cd)。

---

## Task 6: 后台 reaper loop(lifespan)

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/main.py`
- Test: `services/backend/tests/test_reaper_loop.py`

- [ ] **Step 1: 写失败测试(测循环函数,不起真 app)**

Create `services/backend/tests/test_reaper_loop.py`:
```python
import asyncio

import pytest

from agent_cloud_backend.main import _reaper_loop


class _FakeManager:
    def __init__(self):
        self.calls = 0
        self.fired = asyncio.Event()

    async def reap_idle(self) -> int:
        self.calls += 1
        self.fired.set()
        return 0


async def test_reaper_loop_calls_reap_idle_periodically():
    mgr = _FakeManager()
    task = asyncio.create_task(_reaper_loop(0.01, mgr))
    await asyncio.wait_for(mgr.fired.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert mgr.calls >= 1


async def test_reaper_loop_survives_reap_error():
    class _Boom(_FakeManager):
        async def reap_idle(self) -> int:
            self.calls += 1
            self.fired.set()
            raise RuntimeError("boom")

    mgr = _Boom()
    task = asyncio.create_task(_reaper_loop(0.01, mgr))
    await asyncio.wait_for(mgr.fired.wait(), timeout=2)
    # 一次抛错不应让循环退出:稍等应继续被调用
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert mgr.calls >= 2
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_reaper_loop.py -q
```
Expected: FAIL（`_reaper_loop` 不存在)。

- [ ] **Step 3: 实现 lifespan + reaper**

读 `services/backend/src/agent_cloud_backend/main.py`。在文件顶部加导入:
```python
import asyncio
import logging
from contextlib import asynccontextmanager
```
(若已部分存在则合并。)加 logger 与循环 + lifespan(放在 `create_app` 之前):
```python
logger = logging.getLogger(__name__)


async def _reaper_loop(interval_seconds: float, manager) -> None:
    """周期性回收空闲沙箱。单次失败不退出循环。"""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await manager.reap_idle()
        except Exception:
            logger.exception("sandbox reaper pass failed")


@asynccontextmanager
async def lifespan(app):
    from agent_cloud_backend.config import get_settings
    from agent_cloud_backend.sandbox.deps import get_sandbox_manager

    settings = get_settings()
    manager = get_sandbox_manager()
    task = asyncio.create_task(
        _reaper_loop(settings.sandbox_reap_interval_seconds, manager)
    )
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
```
在 `create_app` 里把 lifespan 接上:把 `app = FastAPI(title="Agent Cloud Backend")` 改为
```python
    app = FastAPI(title="Agent Cloud Backend", lifespan=lifespan)
```

- [ ] **Step 4: 跑测试确认通过 + 不回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_reaper_loop.py -q && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_api.py -q
```
Expected: reaper 测试 PASS;现有 API 测试不回归(lifespan 在 testclient 下正常启停)。

- [ ] **Step 5: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/src/agent_cloud_backend/main.py services/backend/tests/test_reaper_loop.py && git commit -m "feat(backend): wire background sandbox reaper in app lifespan"
```

---

## Task 7: work_subdir 接线(docker 用 ".")

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/turn/assemble.py`
- Modify: `services/backend/src/agent_cloud_backend/api/turn.py`(两个端点)
- Test: `services/backend/tests/test_assemble.py`

- [ ] **Step 1: 改失败测试**

读 `services/backend/tests/test_assemble.py`,把对 `build_run_turn_request` 的调用补上 `work_subdir=` 入参,并断言透传。把现有断言
```python
    assert req.work_subdir == s.work_subdir
```
所在的调用改为显式传入,例如(按该测试已有变量名调整):
```python
    req = await build_run_turn_request(
        db, s, sandbox_endpoint="ep", user_message="hi",
        exclude_message_id=None, enabled_skills=[], work_subdir="workspace",
    )
    assert req.work_subdir == "workspace"

    req_docker = await build_run_turn_request(
        db, s, sandbox_endpoint="ep", user_message="hi",
        exclude_message_id=None, enabled_skills=[], work_subdir=".",
    )
    assert req_docker.work_subdir == "."
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_assemble.py -q
```
Expected: FAIL（`build_run_turn_request` 还不接受 `work_subdir` 入参)。

- [ ] **Step 3: build_run_turn_request 加入参**

`services/backend/src/agent_cloud_backend/turn/assemble.py`:给签名加 `work_subdir: str`(keyword-only,放在 `enabled_skills` 后),并把返回里的 `work_subdir=session.work_subdir` 改为 `work_subdir=work_subdir`:
```python
async def build_run_turn_request(
    db: AsyncSession,
    session: Session,
    *,
    sandbox_endpoint: str,
    user_message: str,
    exclude_message_id: uuid.UUID | None,
    enabled_skills: list[Skill] | None = None,
    work_subdir: str,
) -> worker_pb2.RunTurnRequest:
    ...
    return worker_pb2.RunTurnRequest(
        ...
        work_subdir=work_subdir,   # 原: session.work_subdir
    )
```

- [ ] **Step 4: 两个 turn 端点按 provisioner 计算并传入**

`services/backend/src/agent_cloud_backend/api/turn.py`:在 **unary**(`run_turn_endpoint`)与 **stream**(`stream_turn_endpoint`)两处调用 `build_run_turn_request` 前,各加一行计算,并把它传进去(`materialize_enabled_skills(work_subdir=s.work_subdir, ...)` **保持不变**——那是宿主侧 .skills 路径):
```python
        # docker 沙箱:容器已把用户 workspace 挂到 /workspace,沙箱根即 /workspace,
        # 故请求里的 work_subdir 用 "."(避免再嵌套一层 workspace)。inprocess 仍用 "workspace"。
        req_work_subdir = "." if settings.sandbox_provisioner == "docker" else s.work_subdir
        request = await build_run_turn_request(
            db,
            s,
            sandbox_endpoint=sandbox_endpoint,
            user_message=body.content,
            exclude_message_id=user_msg.id,
            enabled_skills=enabled_skills,
            work_subdir=req_work_subdir,
        )
```
(两个端点都这样改;`settings` 在两处都已是 `Depends(get_settings)` 入参。)

- [ ] **Step 5: 跑测试确认通过 + 不回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_assemble.py tests/test_turn_endpoint.py -q
```
Expected: PASS（inprocess 默认下 `work_subdir` 仍 "workspace",`test_turn_endpoint` 的断言不变)。

- [ ] **Step 6: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/src/agent_cloud_backend/turn/assemble.py services/backend/src/agent_cloud_backend/api/turn.py services/backend/tests/test_assemble.py && git commit -m "feat(backend): send work_subdir='.' for docker sandbox (workspace mounted at /workspace)"
```

---

## Task 8: worker→sandbox 连接重试(隐藏冷启动)

**Files:**
- Modify: `services/worker/src/agent_cloud_worker/sandbox_executor.py`
- Test: `services/worker/tests/test_sandbox_executor.py`

> 背景:docker 沙箱 spawn 返回很快(容器已起、gRPC 仍在 boot)。模型先思考几秒才调第一个工具,期间容器就绪。首个工具调用对 `UNAVAILABLE` 短重试即可遮掉冷启动,无需阻塞回合开始。

- [ ] **Step 1: 写失败测试**

在 `services/worker/tests/test_sandbox_executor.py` 追加(若无则创建):
```python
import grpc
import pytest
from agent_cloud_common import ToolCall
from agent_cloud_worker.sandbox_executor import SandboxToolExecutor


class _Resp:
    def __init__(self, content, is_error=False):
        self.content = content
        self.is_error = is_error


class _FlakyRpcError(grpc.aio.AioRpcError):
    def __init__(self):
        pass  # 不调父类 __init__,只实现 code()

    def code(self):
        return grpc.StatusCode.UNAVAILABLE


class _FlakyStub:
    """前 N 次抛 UNAVAILABLE,之后成功。"""

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0

    async def ExecTool(self, req):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise _FlakyRpcError()
        return _Resp("ok")


async def test_execute_retries_unavailable_then_succeeds(monkeypatch):
    ex = SandboxToolExecutor(channel=None, work_subdir=".", max_attempts=5, retry_backoff=0.0)
    ex._stub = _FlakyStub(fail_times=2)  # 头两次 UNAVAILABLE
    res = await ex.execute(ToolCall(id="c1", name="bash", arguments={"command": "echo hi"}))
    assert res.is_error is False and res.content == "ok"
    assert ex._stub.calls == 3


async def test_execute_gives_up_after_max_attempts():
    ex = SandboxToolExecutor(channel=None, work_subdir=".", max_attempts=3, retry_backoff=0.0)
    ex._stub = _FlakyStub(fail_times=99)
    res = await ex.execute(ToolCall(id="c1", name="bash", arguments={"command": "x"}))
    assert res.is_error is True and "UNAVAILABLE" in res.content
    assert ex._stub.calls == 3
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_sandbox_executor.py -q
```
Expected: FAIL（`__init__` 不接受 `max_attempts`/`retry_backoff`;无重试)。

- [ ] **Step 3: 实现重试**

`services/worker/src/agent_cloud_worker/sandbox_executor.py`:顶部加 `import asyncio`。`__init__` 增参:
```python
    def __init__(
        self,
        channel: grpc.aio.Channel,
        work_subdir: str,
        enabled_tools: list[str] | None = None,
        max_attempts: int = 10,
        retry_backoff: float = 1.0,
    ) -> None:
        self._stub = sandbox_pb2_grpc.SandboxStub(channel) if channel is not None else None
        self._work_subdir = work_subdir
        self._enabled_tools = list(enabled_tools or [])
        self._max_attempts = max_attempts
        self._retry_backoff = retry_backoff
```
把 `execute` 的 RPC 段改为带重试(仅对 `UNAVAILABLE` 重试;其它错误立即返回):
```python
        req = sandbox_pb2.ExecToolRequest(
            call_id=call.id,
            tool_name=call.name,
            arguments_json=json.dumps(call.arguments),
            work_subdir=self._work_subdir,
        )
        for attempt in range(self._max_attempts):
            try:
                resp = await self._stub.ExecTool(req)
                return ToolResult(call_id=call.id, content=resp.content, is_error=resp.is_error)
            except grpc.aio.AioRpcError as exc:
                # 沙箱冷启动期可能短暂 UNAVAILABLE:重试遮掉(spec §4.1)。其它错误立即转结果。
                if exc.code() == grpc.StatusCode.UNAVAILABLE and attempt < self._max_attempts - 1:
                    await asyncio.sleep(self._retry_backoff)
                    continue
                return ToolResult(
                    call_id=call.id,
                    content=f"sandbox RPC failed: {exc.code().name}",
                    is_error=True,
                )
```

- [ ] **Step 4: 跑测试确认通过 + 不回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest tests/test_sandbox_executor.py -q && uv run pytest -q
```
Expected: 重试测试 PASS;worker 整套不回归。

- [ ] **Step 5: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/worker/src/agent_cloud_worker/sandbox_executor.py services/worker/tests/test_sandbox_executor.py && git commit -m "feat(worker): retry sandbox ExecTool on UNAVAILABLE (hide container cold start)"
```

---

## Task 9: dev_up.sh 接入 Docker 沙箱

**Files:**
- Modify: `scripts/dev_up.sh`

- [ ] **Step 1: 构建镜像 + 切 provisioner=docker**

读 `scripts/dev_up.sh`。在 `[2/5] migrate` 之后、起 worker 之前,加一步构建沙箱镜像:
```bash
echo "[2.5/5] build sandbox image…"
docker build -f "$ROOT/deploy/sandbox.Dockerfile" -t agent-cloud-sandbox:latest "$ROOT"
```
把 backend 的启动 env 增加沙箱配置(在现有 `AGENT_CLOUD_DATABASE_URL=... uvicorn ...` 那行的 env 里追加):
```bash
  AGENT_CLOUD_SANDBOX_PROVISIONER=docker \
  AGENT_CLOUD_SANDBOX_HOST_ROOT="/tmp/agent-cloud-sandboxes" \
  AGENT_CLOUD_SANDBOX_DOCKER_NETWORK_MODE=publish \
```
> dev:backend/worker 都在宿主,backend 直接用本机 docker(无需挂 socket);`HOST_ROOT` = backend 用的 `SANDBOX_BASE_ROOT`(同一宿主路径);`publish` 模式让 worker 连 `127.0.0.1:<发布端口>`。要回退无隔离的快速模式,把 `PROVISIONER` 设回 `inprocess` 即可。

- [ ] **Step 2: 语法检查**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && bash -n scripts/dev_up.sh && echo "syntax OK"
```
Expected: syntax OK。

- [ ] **Step 3: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add scripts/dev_up.sh && git commit -m "chore(dev_up): build sandbox image + run backend with docker provisioner"
```

---

## Task 10: 隔离 + 依赖持久化集成测试(需真 Docker)

**Files:**
- Test: `services/backend/tests/test_docker_sandbox_isolation.py`

> 这是本方案的安全验收:用真 Docker 起两个用户的沙箱,证明**越权读取被堵**;并证明 **pip 依赖跨容器重建保留**。需镜像已构建(Task 1)。用 `@pytest.mark.docker` 标记,CI 无 Docker 时可 `-m "not docker"` 跳过。

- [ ] **Step 1: 注册 docker mark(避免 pytest 警告)**

在 `services/backend/pyproject.toml` 的 `[tool.pytest.ini_options]` 增加(若无该表则创建):
```toml
markers = ["docker: needs a real Docker daemon + agent-cloud-sandbox image"]
```

- [ ] **Step 2: 写集成测试**

Create `services/backend/tests/test_docker_sandbox_isolation.py`:
```python
import json
import uuid

import grpc
import pytest
from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc

from agent_cloud_backend.sandbox.docker_provisioner import DockerProvisioner

pytestmark = pytest.mark.docker


async def _exec(endpoint: str, tool: str, args: dict, work_subdir: str = "."):
    async with grpc.aio.insecure_channel(endpoint) as ch:
        await grpc.aio.channel_ready_future(ch) if False else None
        stub = sandbox_pb2_grpc.SandboxStub(ch)
        # 容器 boot 可能慢,简单重试
        last = None
        for _ in range(20):
            try:
                resp = await stub.ExecTool(
                    sandbox_pb2.ExecToolRequest(
                        call_id="t", tool_name=tool,
                        arguments_json=json.dumps(args), work_subdir=work_subdir,
                    )
                )
                return resp.content, resp.is_error
            except grpc.aio.AioRpcError as e:
                last = e
                import asyncio

                await asyncio.sleep(0.5)
        raise last


async def test_user_b_cannot_read_user_a_files(tmp_path):
    prov = DockerProvisioner(
        host_root=str(tmp_path), image="agent-cloud-sandbox:latest", network_mode="publish"
    )
    a, b = uuid.uuid4(), uuid.uuid4()
    sid_a, ep_a = await prov.spawn(a)
    sid_b, ep_b = await prov.spawn(b)
    try:
        # A 写一个秘密文件
        _, err = await _exec(ep_a, "write_file", {"path": "secret.txt", "content": "TOP-SECRET"})
        assert err is False
        # 宿主上确认它在 A 的卷里
        assert (tmp_path / str(a) / "workspace" / "secret.txt").read_text() == "TOP-SECRET"

        # B 用 bash 试图按宿主绝对路径读 A 的文件 → 容器里根本没这个路径 → 读不到
        host_path_of_a = str(tmp_path / str(a) / "workspace" / "secret.txt")
        content, err = await _exec(ep_b, "bash", {"command": f"cat {host_path_of_a}"})
        assert "TOP-SECRET" not in content  # 越权失败
        # B 列根目录也看不到别的用户目录
        content, _ = await _exec(ep_b, "bash", {"command": "ls / && ls /workspace"})
        assert str(a) not in content
    finally:
        await prov.stop(sid_a)
        await prov.stop(sid_b)


async def test_pip_dependency_survives_container_respawn(tmp_path):
    prov = DockerProvisioner(
        host_root=str(tmp_path), image="agent-cloud-sandbox:latest", network_mode="publish"
    )
    u = uuid.uuid4()
    sid1, ep1 = await prov.spawn(u)
    try:
        # 装一个小包(默认 PIP_USER=1 → 落进 /workspace/.home/.local)
        out, err = await _exec(
            ep1, "bash", {"command": "pip install --quiet six && python -c 'import six;print(six.__version__)'"}
        )
        assert err is False and out.strip()
    finally:
        await prov.stop(sid1)  # 杀掉容器(冷重建)

    # 同一用户重新 spawn(挂回同卷)→ six 仍能 import
    sid2, ep2 = await prov.spawn(u)
    try:
        out, err = await _exec(ep2, "bash", {"command": "python -c 'import six;print(six.__version__)'"})
        assert err is False and out.strip()  # 依赖跨重建保留
    finally:
        await prov.stop(sid2)
```
> 注:`_exec` 里那行 `channel_ready_future ... if False else None` 是占位,可删;真正的就绪靠下面的重试循环。实现者写时直接用重试循环即可。

- [ ] **Step 3: 跑集成测试(本机有 Docker + 已构建镜像)**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_docker_sandbox_isolation.py -q -m docker
```
Expected: 2 passed——B 读不到 A 的 `TOP-SECRET`、看不到 A 的目录;pip 装的 `six` 跨容器重建仍可 import。

- [ ] **Step 4: 全回归(非 docker 部分)**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q -m "not docker"
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/packages/common && uv run pytest -q
```
Expected: 全绿(docker 集成测试单独按需跑)。

- [ ] **Step 5: ruff + Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && uv run ruff check services/backend services/worker && git add services/backend/tests/test_docker_sandbox_isolation.py services/backend/pyproject.toml && git commit -m "test(backend): docker sandbox cross-user isolation + dependency-persistence integration tests"
```

---

## Self-Review(对照 spec)

- **隔离(spec §1/§9)**:Task 1 镜像 + Task 3 DockerProvisioner(只挂自己 workspace)+ Task 10 验证 B 读不到 A。✔
- **A1 生命周期 + reap(§4/§4.1)**:复用现有 manager/registry/health(Task 4 接 docker provisioner + health_check)+ Task 5(跳过 running)+ Task 6(后台 reaper loop,接上原本无调用方的 reap_idle)。✔
- **路径/卷 + work_subdir="."(§5)**:Task 1(BASE=/workspace)+ Task 7(请求 work_subdir=".",materialize 仍用宿主 workspace 路径)。✔
- **依赖持久化(§8.1)**:Task 1 镜像 env 路由(HOME/PIP_USER/PYTHONUSERBASE/NPM 前缀)+ Task 10 验证 pip 跨重建保留。✔
- **网络(§6)**:Task 3 publish/network 两模式 + Task 9 dev 用 publish。✔
- **配置(§10)**:Task 2 全部配置项。✔
- **冷启动隐藏(§4.1)**:Task 8 worker 对 UNAVAILABLE 重试(spawn 快返回 + 思考期重叠)。✔
- **安全(§9)**:Task 3 cap_drop/no-new-privileges/limits;socket 仅 compose 形态需 proxy(部署文档,非本仓代码;dev 用本机 docker)。✔
- **可插拔/CI 不依赖 Docker**:默认 inprocess(Task 4);docker 集成测试加 mark(Task 10)。✔

类型/签名一致性:`DockerProvisioner.__init__`(host_root/image/network_mode/network/limits/allow_net/client)、`spawn->(uuid,str)`/`stop(uuid)`/`stop_all`、`build_provisioner(settings, docker_client=None)`、`build_run_turn_request(..., work_subdir: str)`、`SandboxToolExecutor(channel, work_subdir, enabled_tools, max_attempts, retry_backoff)`、`_reaper_loop(interval, manager)`、`Settings.effective_sandbox_host_root` —— 跨任务一致。✔

> 未决/留后续(spec 已记):socket-proxy 或最小 provisioner 服务(compose 生产)、`KubernetesProvisioner`、出网 allowlist、requirements/apt 清单重装、gVisor runtime。
