# Docker 沙箱 Provisioner 实现计划(Part 1:镜像 + 配置 + Provisioner + 接线 + reap-skip)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development(推荐)或 superpowers:executing-plans 逐任务实现。步骤用 `- [ ]` 跟踪。Task 6–10 在续写文件 `...-plan-8-docker-sandbox-provisioner-part2.md`。

**Goal:** 给沙箱真正的文件系统隔离——每个用户的沙箱跑在独立 Docker 容器里,只挂载该用户的 workspace 到 `/workspace`,堵住「bash 用绝对路径越权读其他用户文件」的洞;同时保留用户依赖、自动回收空闲容器。

**Architecture:** 新增 `DockerProvisioner` 实现已有的 `SandboxProvisioner` Protocol(`spawn/stop`),用 `docker` Python SDK 借宿主 daemon 起兄弟容器。复用现有 `SandboxManager`/registry/health/reap。配置 `AGENT_CLOUD_SANDBOX_PROVISIONER=inprocess|docker` 选择(默认 inprocess,CI 不依赖 Docker)。依赖经 `HOME`/`PIP_USER`/`PYTHONUSERBASE`/`NPM_CONFIG_PREFIX` 等 env 路由进 `/workspace` 卷以跨重建保留。

**Tech Stack:** Python 3.13, Docker (Python SDK `docker`), FastAPI, grpc.aio, pytest, pydantic-settings。

**对应 spec:** `docs/superpowers/specs/2026-06-07-docker-sandbox-provisioner-design.md`。

---

## 测试 / 命令约定

- backend 测试在 `services/backend` 下:`cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest <args>`。
- 纯单元测试(不碰 testcontainers/Docker)可省 RYUK,但带上无害。
- 每条命令用绝对路径 `cd`(shell cwd 跨命令保持,但显式 cd 更稳)。
- 需要真 Docker 的集成测试用 `@pytest.mark.docker` 标记,默认可在本机跑、CI 可跳过。

## 文件结构(Part 1 + 2 全程)

```
deploy/
  sandbox.Dockerfile            # 沙箱镜像:sandbox 服务 + python + 依赖路由 env
  sandbox-entrypoint.sh         # 建 HOME/.local 等目录后 exec 沙箱服务
services/backend/src/agent_cloud_backend/
  config.py                     # (改)新增 sandbox provisioner / docker / reap 配置
  sandbox/docker_provisioner.py # (新)DockerProvisioner
  sandbox/deps.py               # (改)按配置选 InProcess / Docker
  sandbox/manager.py            # (改)reap_idle 跳过 running 会话
  repositories/session.py       # (改)查"有 running 会话的用户"
  repositories/sandbox_registry.py # (可能改)给 reap 提供 user_id
  turn/assemble.py              # (改)work_subdir 作为入参(docker 用 ".")
  api/turn.py                   # (改)按 provisioner 计算 work_subdir;并发预热(part2)
  main.py                       # (改)lifespan 起后台 reaper(part2)
services/worker/src/agent_cloud_worker/
  sandbox_executor.py           # (改)ExecTool 对 UNAVAILABLE 短重试(part2)
scripts/dev_up.sh               # (改)构建沙箱镜像 + PROVISIONER=docker(part2)
services/backend/tests/         # 各任务对应单元/集成测试
```

---

## Task 1: 沙箱 Docker 镜像

**Files:**
- Create: `deploy/sandbox.Dockerfile`
- Create: `deploy/sandbox-entrypoint.sh`

- [ ] **Step 1: 入口脚本**

Create `deploy/sandbox-entrypoint.sh`:
```bash
#!/usr/bin/env sh
# /workspace 是挂进来的用户卷,新用户初始为空。先建好依赖路由目录(HOME / pip --user /
# npm 前缀),再启动沙箱服务。这些目录在卷里 → 装的依赖跨容器重建保留。
set -e
mkdir -p /workspace/.home/.local/bin /workspace/.home/.cache /workspace/.npm-global/bin
exec python -m agent_cloud_sandbox
```

- [ ] **Step 2: Dockerfile**

Create `deploy/sandbox.Dockerfile`:
```dockerfile
FROM python:3.13-slim

# 依赖路由:让 pip/npm 等把包装进 /workspace 卷(跨容器重建保留)。详见 spec §8.1。
ENV HOME=/workspace/.home \
    PYTHONUSERBASE=/workspace/.home/.local \
    PIP_USER=1 \
    PIP_CACHE_DIR=/workspace/.home/.cache/pip \
    NPM_CONFIG_PREFIX=/workspace/.npm-global \
    npm_config_cache=/workspace/.home/.npm \
    XDG_DATA_HOME=/workspace/.home/.local/share \
    XDG_CACHE_HOME=/workspace/.home/.cache \
    PATH=/workspace/.home/.local/bin:/workspace/.npm-global/bin:/usr/local/bin:/usr/bin:/bin \
    AGENT_CLOUD_SANDBOX_BASE=/workspace \
    AGENT_CLOUD_SANDBOX_PORT=50051 \
    PYTHONUNBUFFERED=1

# 沙箱服务 + 其依赖(common)。从仓库根构建:`docker build -f deploy/sandbox.Dockerfile .`
WORKDIR /app
COPY packages/common /app/packages/common
COPY services/sandbox /app/services/sandbox
RUN pip install --no-cache-dir --no-user /app/packages/common /app/services/sandbox

COPY deploy/sandbox-entrypoint.sh /usr/local/bin/sandbox-entrypoint.sh
RUN chmod +x /usr/local/bin/sandbox-entrypoint.sh

EXPOSE 50051
CMD ["/usr/local/bin/sandbox-entrypoint.sh"]
```
> 注:`pip install` 这里要 `--no-user`(覆盖 `PIP_USER=1`),否则装到 `/workspace`(构建期无卷)而不是镜像。运行期用户 `pip install` 才走 `--user`→`/workspace`。

- [ ] **Step 3: 构建镜像**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && docker build -f deploy/sandbox.Dockerfile -t agent-cloud-sandbox:latest .
```
Expected: 构建成功,出现 `agent-cloud-sandbox:latest`(`docker images | grep agent-cloud-sandbox`)。

- [ ] **Step 4: 冒烟——容器内沙箱可执行工具 + 依赖路由**

Run(起容器、挂临时卷、确认服务起来 + pip --user 落到卷):
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
rm -rf /tmp/sbx-smoke && mkdir -p /tmp/sbx-smoke
docker run -d --rm --name sbx-smoke -v /tmp/sbx-smoke:/workspace -p 50061:50051 agent-cloud-sandbox:latest
sleep 2
docker logs sbx-smoke           # 期望: sandbox listening on 0.0.0.0:50051 (base=/workspace)
docker exec sbx-smoke sh -c 'cd /workspace && echo hi > a.txt && cat a.txt'   # 期望: hi
docker exec sbx-smoke sh -c 'pip install --quiet requests && python -c "import requests; print(requests.__version__)"'
ls /tmp/sbx-smoke/.home/.local/lib/python*/site-packages/ | grep -i requests   # 期望: requests 落在卷里
docker stop sbx-smoke
```
Expected: 日志显示监听;a.txt 读回 `hi`;requests 装好且 `/tmp/sbx-smoke/.home/.local/.../requests` 存在(证明 pip 依赖落进 /workspace 卷)。

- [ ] **Step 5: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add deploy/sandbox.Dockerfile deploy/sandbox-entrypoint.sh && git commit -m "feat(deploy): sandbox Docker image (server + python, deps routed into /workspace volume)"
```

---

## Task 2: backend 配置项

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/config.py`
- Test: `services/backend/tests/test_config.py`

- [ ] **Step 1: 写失败测试**

在 `services/backend/tests/test_config.py` 末尾追加(若文件不存在则创建并加 `from agent_cloud_backend.config import Settings`):
```python
def test_sandbox_provisioner_defaults():
    s = Settings(_env_file=None)
    assert s.sandbox_provisioner == "inprocess"
    assert s.sandbox_image == "agent-cloud-sandbox:latest"
    assert s.sandbox_docker_network_mode == "publish"
    assert s.sandbox_idle_ttl_seconds == 1800
    assert s.sandbox_reap_interval_seconds == 120
    assert s.sandbox_allow_net is True


def test_sandbox_host_root_defaults_to_base_root():
    s = Settings(_env_file=None)
    # 未单独配置 host_root 时,回退到 sandbox_base_root(开发机 backend 在宿主,二者相同)
    assert s.effective_sandbox_host_root == s.sandbox_base_root


def test_sandbox_provisioner_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_SANDBOX_PROVISIONER", "docker")
    monkeypatch.setenv("AGENT_CLOUD_SANDBOX_HOST_ROOT", "/srv/ac/sandboxes")
    s = Settings()
    assert s.sandbox_provisioner == "docker"
    assert s.effective_sandbox_host_root == "/srv/ac/sandboxes"
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_config.py -q
```
Expected: FAIL（`Settings` 无 `sandbox_provisioner` 等属性）。

- [ ] **Step 3: 加配置字段**

读 `services/backend/src/agent_cloud_backend/config.py` 确认现有字段(`database_url` / `worker_endpoint` / `sandbox_base_root` / `object_store_root`),在 `Settings` 类体内、`object_store_root` 之后追加:
```python
    # ── 沙箱 provisioner(spec: docker-sandbox-provisioner-design)──
    sandbox_provisioner: str = "inprocess"  # inprocess | docker
    sandbox_host_root: str = ""  # DooD 下宿主 workspace 根;空=回退 sandbox_base_root
    sandbox_image: str = "agent-cloud-sandbox:latest"
    sandbox_docker_network_mode: str = "publish"  # publish(dev) | network(prod)
    sandbox_docker_network: str = "agent-cloud-net"
    sandbox_mem_limit: str = "512m"
    sandbox_nano_cpus: int = 1_000_000_000  # 1 vCPU
    sandbox_pids_limit: int = 256
    sandbox_allow_net: bool = True
    sandbox_idle_ttl_seconds: int = 1800
    sandbox_reap_interval_seconds: int = 120

    @property
    def effective_sandbox_host_root(self) -> str:
        return self.sandbox_host_root or self.sandbox_base_root
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_config.py -q
```
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/src/agent_cloud_backend/config.py services/backend/tests/test_config.py && git commit -m "feat(backend): sandbox provisioner config (provisioner/host_root/image/network/limits/ttl)"
```

---

## Task 3: DockerProvisioner

**Files:**
- Create: `services/backend/src/agent_cloud_backend/sandbox/docker_provisioner.py`
- Test: `services/backend/tests/test_docker_provisioner.py`

- [ ] **Step 1: 写失败测试(用假 docker client,不碰真 Docker)**

Create `services/backend/tests/test_docker_provisioner.py`:
```python
import uuid

import pytest

from agent_cloud_backend.sandbox.docker_provisioner import DockerProvisioner


class _FakeContainer:
    def __init__(self, name):
        self.name = name
        self.ports = {"50051/tcp": [{"HostPort": "49222"}]}
        self.stopped = False
        self.removed = False

    def reload(self):
        pass

    def stop(self, timeout=5):
        self.stopped = True

    def remove(self, force=False):
        self.removed = True


class _FakeContainers:
    def __init__(self):
        self.run_kwargs = None
        self.by_name = {}

    def run(self, **kwargs):
        self.run_kwargs = kwargs
        c = _FakeContainer(kwargs["name"])
        self.by_name[kwargs["name"]] = c
        return c

    def get(self, name):
        from docker.errors import NotFound

        if name not in self.by_name:
            raise NotFound(name)
        return self.by_name[name]

    def list(self, all=False, filters=None):
        return list(self.by_name.values())


class _FakeClient:
    def __init__(self):
        self.containers = _FakeContainers()


async def test_spawn_publish_mode_mounts_workspace_and_returns_localhost_endpoint(tmp_path):
    client = _FakeClient()
    prov = DockerProvisioner(
        host_root=str(tmp_path), image="img:1", network_mode="publish", client=client
    )
    uid = uuid.uuid4()
    sandbox_id, endpoint = await prov.spawn(uid)

    kw = client.containers.run_kwargs
    # 只挂该用户的 workspace 到 /workspace
    assert kw["volumes"] == {f"{tmp_path}/{uid}/workspace": {"bind": "/workspace", "mode": "rw"}}
    assert kw["image"] == "img:1"
    assert kw["detach"] is True
    assert kw["cap_drop"] == ["ALL"]
    assert "no-new-privileges" in kw["security_opt"][0]
    assert kw["labels"]["managed-by"] == "agent-cloud"
    assert kw["labels"]["user_id"] == str(uid)
    assert kw["ports"] == {"50051/tcp": None}  # 发布随机宿主端口
    assert kw["name"] == f"acsbx-{sandbox_id}"  # 按 sandbox_id 命名 → 重启后可按名找回
    assert endpoint == "127.0.0.1:49222"


async def test_spawn_network_mode_uses_container_name_endpoint(tmp_path):
    client = _FakeClient()
    prov = DockerProvisioner(
        host_root=str(tmp_path), image="img:1", network_mode="network",
        network="acnet", client=client,
    )
    sandbox_id, endpoint = await prov.spawn(uuid.uuid4())
    kw = client.containers.run_kwargs
    assert kw["network"] == "acnet"
    assert "ports" not in kw
    assert endpoint == f"acsbx-{sandbox_id}:50051"


async def test_stop_is_idempotent_when_container_missing(tmp_path):
    client = _FakeClient()
    prov = DockerProvisioner(host_root=str(tmp_path), image="img:1", client=client)
    await prov.stop(uuid.uuid4())  # 容器不存在 → 不抛


async def test_stop_stops_and_removes(tmp_path):
    client = _FakeClient()
    prov = DockerProvisioner(host_root=str(tmp_path), image="img:1", client=client)
    sandbox_id, _ = await prov.spawn(uuid.uuid4())
    await prov.stop(sandbox_id)
    c = client.containers.by_name[f"acsbx-{sandbox_id}"]
    assert c.stopped and c.removed
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_docker_provisioner.py -q
```
Expected: FAIL（模块不存在)。先确保 `docker` SDK 已装:`cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv add docker`。

- [ ] **Step 3: 实现 DockerProvisioner**

Create `services/backend/src/agent_cloud_backend/sandbox/docker_provisioner.py`:
```python
from __future__ import annotations

import asyncio
import logging
import os
import uuid

logger = logging.getLogger(__name__)

_SANDBOX_PORT = "50051"
_LABEL = "agent-cloud"


class DockerProvisioner:
    """借宿主 Docker daemon 起每用户沙箱容器(DooD)。实现 SandboxProvisioner Protocol。

    隔离:容器只挂载该用户的 <host_root>/<user_id>/workspace 到 /workspace,宿主机其它
    用户目录在容器内不存在 → 跨用户越权读取被堵(spec §1/§9)。docker SDK 是同步的,
    全部调用包进 asyncio.to_thread 以不阻塞事件循环。
    """

    def __init__(
        self,
        *,
        host_root: str,
        image: str,
        network_mode: str = "publish",
        network: str = "agent-cloud-net",
        mem_limit: str = "512m",
        nano_cpus: int = 1_000_000_000,
        pids_limit: int = 256,
        allow_net: bool = True,
        client=None,
    ) -> None:
        self._host_root = str(host_root)
        self._image = image
        self._network_mode = network_mode
        self._network = network
        self._mem_limit = mem_limit
        self._nano_cpus = nano_cpus
        self._pids_limit = pids_limit
        self._allow_net = allow_net
        if client is None:
            import docker

            client = docker.from_env()
        self._client = client

    async def spawn(self, user_id: uuid.UUID) -> tuple[uuid.UUID, str]:
        sandbox_id = uuid.uuid4()
        name = f"acsbx-{sandbox_id}"
        host_ws = f"{self._host_root}/{user_id}/workspace"
        os.makedirs(host_ws, exist_ok=True)  # bind 源目录必须存在
        kwargs: dict = dict(
            image=self._image,
            detach=True,
            name=name,
            volumes={host_ws: {"bind": "/workspace", "mode": "rw"}},
            labels={"managed-by": _LABEL, "user_id": str(user_id)},
            mem_limit=self._mem_limit,
            nano_cpus=self._nano_cpus,
            pids_limit=self._pids_limit,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
        )
        if self._network_mode == "network":
            kwargs["network"] = self._network
            endpoint = f"{name}:{_SANDBOX_PORT}"
        else:  # publish:发布随机宿主端口,worker 在宿主连 localhost
            kwargs["ports"] = {f"{_SANDBOX_PORT}/tcp": None}
            endpoint = ""
        container = await asyncio.to_thread(self._client.containers.run, **kwargs)
        if self._network_mode != "network":
            await asyncio.to_thread(container.reload)
            host_port = container.ports[f"{_SANDBOX_PORT}/tcp"][0]["HostPort"]
            endpoint = f"127.0.0.1:{host_port}"
        logger.info("spawned sandbox %s for user %s at %s", sandbox_id, user_id, endpoint)
        return sandbox_id, endpoint

    async def stop(self, sandbox_id: uuid.UUID) -> None:
        name = f"acsbx-{sandbox_id}"

        def _stop() -> None:
            from docker.errors import NotFound

            try:
                c = self._client.containers.get(name)
            except NotFound:
                return  # 已不在 → no-op(Protocol 要求未知 id 视为 no-op)
            try:
                c.stop(timeout=5)
            finally:
                c.remove(force=True)

        await asyncio.to_thread(_stop)

    async def stop_all(self) -> None:
        """停掉本系统起的所有沙箱容器(测试 teardown / 运维清理)。按 label 找。"""

        def _all() -> None:
            for c in self._client.containers.list(
                all=True, filters={"label": f"managed-by={_LABEL}"}
            ):
                try:
                    c.stop(timeout=5)
                    c.remove(force=True)
                except Exception:
                    logger.exception("failed to stop sandbox container %s", getattr(c, "name", "?"))

        await asyncio.to_thread(_all)
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_docker_provisioner.py -q
```
Expected: 4 passed。

- [ ] **Step 5: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/src/agent_cloud_backend/sandbox/docker_provisioner.py services/backend/tests/test_docker_provisioner.py services/backend/pyproject.toml services/backend/uv.lock && git commit -m "feat(backend): DockerProvisioner (per-user container, workspace->/workspace, hardened, DooD)"
```

---

## Task 4: deps.py 按配置选 provisioner

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/sandbox/deps.py`
- Test: `services/backend/tests/test_sandbox_deps.py`

- [ ] **Step 1: 写失败测试**

Create `services/backend/tests/test_sandbox_deps.py`:
```python
from agent_cloud_backend.config import Settings
from agent_cloud_backend.sandbox.deps import build_provisioner
from agent_cloud_backend.sandbox.docker_provisioner import DockerProvisioner
from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner


def test_build_provisioner_inprocess_by_default():
    s = Settings(_env_file=None)
    assert isinstance(build_provisioner(s), InProcessProvisioner)


def test_build_provisioner_docker_when_configured(monkeypatch):
    monkeypatch.setenv("AGENT_CLOUD_SANDBOX_PROVISIONER", "docker")
    monkeypatch.setenv("AGENT_CLOUD_SANDBOX_HOST_ROOT", "/srv/ac")
    s = Settings()
    # 不连真 Docker:注入假 client
    prov = build_provisioner(s, docker_client=object())
    assert isinstance(prov, DockerProvisioner)
    assert prov._host_root == "/srv/ac"
    assert prov._image == s.sandbox_image
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_sandbox_deps.py -q
```
Expected: FAIL（`build_provisioner` 不存在)。

- [ ] **Step 3: 实现 build_provisioner 并接入 get_sandbox_manager**

读现有 `services/backend/src/agent_cloud_backend/sandbox/deps.py`,整体替换为:
```python
from __future__ import annotations

from pathlib import Path

from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.sandbox.docker_provisioner import DockerProvisioner
from agent_cloud_backend.sandbox.health import grpc_endpoint_alive
from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner
from agent_cloud_backend.sandbox.manager import SandboxManager
from agent_cloud_backend.sandbox.provisioner import SandboxProvisioner

_manager: SandboxManager | None = None


def build_provisioner(settings: Settings, docker_client=None) -> SandboxProvisioner:
    """按配置造 provisioner。docker_client 仅测试注入。"""
    if settings.sandbox_provisioner == "docker":
        return DockerProvisioner(
            host_root=settings.effective_sandbox_host_root,
            image=settings.sandbox_image,
            network_mode=settings.sandbox_docker_network_mode,
            network=settings.sandbox_docker_network,
            mem_limit=settings.sandbox_mem_limit,
            nano_cpus=settings.sandbox_nano_cpus,
            pids_limit=settings.sandbox_pids_limit,
            allow_net=settings.sandbox_allow_net,
            client=docker_client,
        )
    return InProcessProvisioner(base_root=Path(settings.sandbox_base_root))


def get_sandbox_manager() -> SandboxManager:
    """进程级单例 SandboxManager。测试通过 app.dependency_overrides 注入自己的 manager。"""
    global _manager
    if _manager is None:
        settings = get_settings()
        _manager = SandboxManager(
            provisioner=build_provisioner(settings),
            sessionmaker=get_sessionmaker(),
            idle_ttl_seconds=settings.sandbox_idle_ttl_seconds,
            health_check=grpc_endpoint_alive,
        )
    return _manager
```

- [ ] **Step 4: 跑测试确认通过 + 不回归**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_sandbox_deps.py -q && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_sandbox_manager.py -q
```
Expected: 新测试 PASS;manager 测试不回归(若无 test_sandbox_manager.py 则跳过该文件,只跑前者)。

- [ ] **Step 5: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/src/agent_cloud_backend/sandbox/deps.py services/backend/tests/test_sandbox_deps.py && git commit -m "feat(backend): select sandbox provisioner by config (inprocess|docker)"
```

---

## Task 5: reap_idle 跳过 running 会话

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/repositories/session.py`(加查询)
- Modify: `services/backend/src/agent_cloud_backend/sandbox/manager.py`(reap 过滤)
- Test: `services/backend/tests/test_sandbox_manager.py`(新增/追加)

- [ ] **Step 1: 写失败测试**

在 `services/backend/tests/test_sandbox_manager.py` 追加(若无此文件则创建;沿用该目录现有 manager 测试夹具风格,用真 sessionmaker + 假 provisioner)。本测试要点:有 `running` 会话的用户,其空闲沙箱**不被 reap**。
```python
async def test_reap_skips_user_with_running_session(make_manager, seed_idle_sandbox, set_session_running):
    # seed_idle_sandbox: 给 user 造一个 last_used_at 远超 TTL 的 active 沙箱
    # set_session_running: 给同一 user 造一个 status="running" 的 session
    manager, user_id = await seed_idle_sandbox(idle_seconds=99999)
    await set_session_running(user_id)
    reaped = await manager.reap_idle()
    assert reaped == 0  # 有 running 会话 → 跳过,不回收
```
> 若该测试文件/夹具不存在,实现者据本仓库 `services/backend/tests` 现有夹具(`session` sessionmaker、`SandboxRegistryRepository`、`SessionRepository`)自行搭最小夹具:插入一条 `sandbox_registry`(active、`last_used_at = now-99999s`)+ 一条 `sessions`(`status="running"`),用注入假 provisioner 的 `SandboxManager(idle_ttl_seconds=1800)` 调 `reap_idle()`,断言返回 0 且该沙箱仍 active。再加一个对照:无 running 会话时该沙箱被回收(返回 1)。

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_sandbox_manager.py -q
```
Expected: FAIL（当前 reap 不看会话状态,会把它回收 → reaped==1)。

- [ ] **Step 3: 加"有 running 会话的用户"查询**

在 `services/backend/src/agent_cloud_backend/repositories/session.py` 的 `SessionRepository` 内追加方法:
```python
    async def user_ids_with_running_session(self, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        """给定用户里,哪些当前有 status='running' 的会话(用于 reap 时跳过)。"""
        if not user_ids:
            return set()
        result = await self.session.execute(
            select(Session.user_id)
            .where(Session.user_id.in_(user_ids), Session.status == "running")
            .distinct()
        )
        return set(result.scalars().all())
```
(确认 `session.py` 顶部已 `from sqlalchemy import select`,已有则不动;`Session` 已导入。)

- [ ] **Step 4: reap_idle 过滤掉这些用户**

`services/backend/src/agent_cloud_backend/sandbox/manager.py`:`reap_idle` 里拿到 `stale` 后,排除 user 有 running 会话的沙箱。把这段:
```python
        cutoff = datetime.now(UTC) - timedelta(seconds=self._idle_ttl_seconds)
        async with self._sessionmaker() as db:
            stale = await SandboxRegistryRepository(db).list_active_idle_since(cutoff)
            stale_ids = [s.id for s in stale]
```
改为:
```python
        from agent_cloud_backend.repositories.session import SessionRepository

        cutoff = datetime.now(UTC) - timedelta(seconds=self._idle_ttl_seconds)
        async with self._sessionmaker() as db:
            stale = await SandboxRegistryRepository(db).list_active_idle_since(cutoff)
            # 跳过仍有 running 会话的用户:long-running 回合期间 last_used_at 不续,
            # 不排除会被中途回收(spec §4.1)。
            busy = await SessionRepository(db).user_ids_with_running_session(
                [s.user_id for s in stale]
            )
            stale_ids = [s.id for s in stale if s.user_id not in busy]
```
> 确认 `list_active_idle_since` 返回的行带 `user_id` 字段(`sandbox_registry` 模型有 `user_id`)。若没有现成 `user_id` 属性,在 `SandboxRegistry` 模型/查询里它本就存在(registry 按 user 建)。

- [ ] **Step 5: 跑测试确认通过**

Run:
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_sandbox_manager.py -q
```
Expected: PASS(running 会话的沙箱被跳过;对照组被回收)。

- [ ] **Step 6: Commit**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud && git add services/backend/src/agent_cloud_backend/repositories/session.py services/backend/src/agent_cloud_backend/sandbox/manager.py services/backend/tests/test_sandbox_manager.py && git commit -m "feat(backend): reap_idle skips users with a running session (no mid-turn reap)"
```

---

> **Part 2(Task 6–10:后台 reaper loop、work_subdir 接线、worker 连接重试、dev_up.sh、隔离+依赖持久化集成测试)见 `2026-06-07-plan-8-docker-sandbox-provisioner-part2.md`。**
