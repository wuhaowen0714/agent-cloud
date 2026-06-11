# 沙箱跨租户隔离(B + C)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 堵住沙箱跨租户穿透:token 鉴权(连到端口≠能执行)+ per-sandbox 网络(沙箱够不到 db/backend/邻居)+ 强密码 + 安全文档。

**Architecture:** C②token = proto 加字段 + 沙箱 server gRPC 拦截器 + provisioner 注入 + registry 落库 + turn 透传 + worker metadata(跨平台永久)。B 网络 = 仅 `DockerProvisioner` 内部的 per-sandbox docker network 生命周期(network 模式)。C①强密码 = compose/.env。

**Tech Stack:** gRPC(aio interceptor)+ docker SDK + FastAPI + Alembic + pytest(`@pytest.mark.docker` 本地跑、CI 跳)。

参考 spec:`docs/superpowers/specs/2026-06-11-sandbox-isolation-design.md`(5590e14)

backend 测试:`cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q`;docker 测试去掉 `-m "not docker"` 并需本地镜像。

---

## Task SI-1: 安全文档(D)

**Files:** Create `docs/security/sandbox-isolation.md`

- [ ] 写文档,两层结构(便于 k8s 迁移只换实现章):
  - **威胁模型 / 隔离目标(永久)**:多租户 + agent 自主执行 + prompt-injection 攻陷源;信任边界(LLM key 仅 worker,沙箱最不可信);**现状漏洞可达性表**(network 模式全员同网 → 沙箱直连邻居 :50051 零认证 ExecTool / 直连 db:5432 弱密码);**隔离目标**(沙箱间互不可达、够不到 db/backend、出公网受控、连到端口≠能执行)。
  - **实现(分平台)**:docker 单机 = 本次 B+C(token 鉴权 + per-sandbox 网络 + 强密码);k8s 未来 = NetworkPolicy 替代网络隔离、Secret 承载密码、token 原样复用、起 Pod 经 k8s API、workspace 走 RWX PVC(更根本的迁移瓶颈,正交不在本次)。
  - **残留风险**:沙箱仍能连 worker:50052(无 key 调不动 RunTurn,至多 DoS;后续给 worker 加 token);egress 出网未限(独立 allowlist,roadmap 在册);token 落 registry 表明文(db 已被强密码+摘网络保护,db 被打穿时攻击者已赢)。
  - **运维:改 db 密码步骤**(C① 配套):首次部署设 `AGENT_CLOUD_DB_PASSWORD`;已有部署改密码需 `ALTER ROLE postgres PASSWORD '…'` 或重建 db 卷(给命令)。
- [ ] 提交 `docs: sandbox cross-tenant isolation security doc`

## Task SI-2: postgres 强密码(C①)

**Files:** Modify `deploy/compose.yml`;Create `deploy/.env.example`

- [ ] `compose.yml`:`db.environment.POSTGRES_PASSWORD` 改为 `${AGENT_CLOUD_DB_PASSWORD:?set AGENT_CLOUD_DB_PASSWORD in deploy/.env}`;`backend.environment.AGENT_CLOUD_DATABASE_URL` 的 `postgres:postgres@db` 改为 `postgres:${AGENT_CLOUD_DB_PASSWORD}@db`。
- [ ] `deploy/.env.example`:加 `AGENT_CLOUD_DB_PASSWORD=` 一行 + 注释"强随机值,勿用默认;改已有部署见 docs/security/sandbox-isolation.md"。
- [ ] 验证:`cd deploy && AGENT_CLOUD_DB_PASSWORD= docker compose config 2>&1 | grep -q "set AGENT_CLOUD_DB_PASSWORD"` 或目视 `docker compose -f deploy/compose.yml config` 在未设变量时报错(fail-loud)。无自动化测试。
- [ ] 提交 `feat(deploy): postgres password from env, fail-loud (no weak default)`

## Task SI-3: proto sandbox_token(C②-a)

**Files:** Modify `protos/agent_cloud/v1/worker.proto`;regen

- [ ] `RunTurnRequest` 末尾(`work_subdir = 10` 后)加 `string sandbox_token = 11;`(注释:沙箱 gRPC 鉴权 token,backend 注入;空=不校验)。
- [ ] `bash scripts/gen_protos.sh` 重新生成。
- [ ] 提交 `feat(proto): RunTurnRequest.sandbox_token`

## Task SI-4: 沙箱 server token 拦截器(C②-b)

**Files:** Modify `services/sandbox/src/agent_cloud_sandbox/server.py`、`services/sandbox/src/agent_cloud_sandbox/__main__.py`;Create `services/sandbox/tests/test_token_auth.py`

- [ ] **Step 1: 失败测试**(test_token_auth.py):

```python
import grpc
import pytest
from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc
from agent_cloud_sandbox.server import create_server


async def _exec(port, token_md):
    md = (("x-sandbox-token", token_md),) if token_md is not None else ()
    async with grpc.aio.insecure_channel(f"localhost:{port}") as ch:
        stub = sandbox_pb2_grpc.SandboxStub(ch)
        return await stub.ExecTool(
            sandbox_pb2.ExecToolRequest(call_id="t", tool_name="bash",
                                        arguments_json='{"command": "echo hi"}', work_subdir="."),
            metadata=md,
        )


async def test_token_required_when_configured(tmp_path):
    server, port = await create_server(tmp_path, host="localhost", port=0, token="sekret")
    try:
        resp = await _exec(port, "sekret")
        assert resp.is_error is False
        with pytest.raises(grpc.aio.AioRpcError) as ei:
            await _exec(port, "wrong")
        assert ei.value.code() == grpc.StatusCode.UNAUTHENTICATED
        with pytest.raises(grpc.aio.AioRpcError) as ei2:
            await _exec(port, None)  # 不带 metadata
        assert ei2.value.code() == grpc.StatusCode.UNAUTHENTICATED
    finally:
        await server.stop(None)


async def test_no_token_means_open(tmp_path):
    # 向后兼容:未配 token → 不校验(inprocess/CI/旧镜像)
    server, port = await create_server(tmp_path, host="localhost", port=0)
    try:
        resp = await _exec(port, None)
        assert resp.is_error is False
    finally:
        await server.stop(None)
```

- [ ] **Step 2: 确认失败** — `cd services/sandbox && uv run pytest tests/test_token_auth.py -q`,Expected: `create_server` 不接受 `token` 参数 / 无校验。
- [ ] **Step 3: 实现** — `server.py` 顶部加拦截器,`create_server` 加 `token` 参数:

```python
class _TokenInterceptor(grpc.aio.ServerInterceptor):
    """校验调用方 metadata 的 x-sandbox-token;不符 → UNAUTHENTICATED。
    token 为空时本拦截器根本不装(见 create_server)→ 开放(向后兼容)。"""

    def __init__(self, token: str) -> None:
        self._token = token

    async def intercept_service(self, continuation, handler_call_details):
        md = dict(handler_call_details.invocation_metadata or ())
        if md.get("x-sandbox-token") != self._token:
            async def _deny(request, context):
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid sandbox token")
            return grpc.aio.unary_unary_rpc_method_handler(_deny)
        return await continuation(handler_call_details)
```

```python
async def create_server(
    base_workdir: Path, host: str = "localhost", port: int = 0, token: str = ""
) -> tuple[grpc.aio.Server, int]:
    interceptors = [_TokenInterceptor(token)] if token else []
    server = grpc.aio.server(interceptors=interceptors)
    sandbox_pb2_grpc.add_SandboxServicer_to_server(SandboxServicer(base_workdir), server)
    bound_port = server.add_insecure_port(f"{host}:{port}")
    await server.start()
    return server, bound_port
```

`__main__.py`:`token = os.environ.get("AGENT_CLOUD_SANDBOX_TOKEN", "")` 传入 `create_server(..., token=token)`。

- [ ] **Step 4: 测试过** — 同 Step 2 命令,Expected: PASS;`cd services/sandbox && uv run pytest -q` 全过。
- [ ] **Step 5: 提交** `feat(sandbox): optional per-sandbox token auth on ExecTool`

## Task SI-5: registry 列 + provisioner 三元组 + manager SandboxConn(C②-c)

**Files:** Modify `models/sandbox_registry.py`、`repositories/sandbox_registry.py`、`sandbox/provisioner.py`、`sandbox/inprocess.py`、`sandbox/docker_provisioner.py`、`sandbox/manager.py`;Create `alembic/versions/<rev>_sandbox_auth_token.py`;Test `services/backend/tests/test_sandbox_manager.py`(既有,补用例)

- [ ] **Step 1: 失败测试**(test_sandbox_manager.py 追加;若文件不存在则建,沿用既有 manager 测试的 fake provisioner 风格):

```python
async def test_get_endpoint_returns_conn_with_token(engine):
    from agent_cloud_backend.sandbox.manager import SandboxConn, SandboxManager
    from sqlalchemy.ext.asyncio import async_sessionmaker
    import uuid

    class _FakeProv:
        async def spawn(self, user_id):
            return uuid.uuid4(), "sbx:50051", "tok-123"
        async def stop(self, sandbox_id):
            pass

    mgr = SandboxManager(_FakeProv(), async_sessionmaker(engine, expire_on_commit=False))
    conn = await mgr.get_endpoint_for_user(uuid.uuid4())
    assert isinstance(conn, SandboxConn)
    assert conn.endpoint == "sbx:50051" and conn.token == "tok-123"
```

- [ ] **Step 2: 确认失败** — `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_sandbox_manager.py -q`,Expected: 无 SandboxConn / spawn 解包 2 元组失败。
- [ ] **Step 3: 实现**:
  - `models/sandbox_registry.py`:加 `auth_token: Mapped[str] = mapped_column(default="", nullable=False)`。
  - migration(参照 `a1b2c3d4e5f6` 风格;`down_revision` 指向当前 head——用 `cd services/backend && uv run alembic heads` 确认):`op.add_column("sandbox_registry", sa.Column("auth_token", sa.String(), nullable=False, server_default=""))`,downgrade `op.drop_column`。
  - `repositories/sandbox_registry.py`:`register(self, sandbox_id, user_id, endpoint, token="")` → `SandboxRegistry(..., auth_token=token)`。
  - `sandbox/provisioner.py`:Protocol `spawn` 返回类型改 `tuple[uuid.UUID, str, str]`,docstring 注明第三元为 token。
  - `sandbox/inprocess.py`:`spawn` 返回 `(sandbox_id, f"localhost:{port}", "")`(空 token);其 `create_server` 不传 token → 开放。
  - `sandbox/docker_provisioner.py`:`spawn` 顶部 `token = secrets.token_urlsafe(32)`;`kwargs` 加 `environment={"AGENT_CLOUD_SANDBOX_TOKEN": token}`;返回 `(sandbox_id, endpoint, token)`(`import secrets`)。
  - `sandbox/manager.py`:顶部加 `@dataclass(frozen=True) class SandboxConn: endpoint: str; token: str`;`get_endpoint_for_user` 返回类型 `SandboxConn`;三处 return 改:复用 `SandboxConn(existing.endpoint, existing.auth_token)`、正常 `SandboxConn(endpoint, token)`、race winner `SandboxConn(winner.endpoint, winner.auth_token)`;spawn 解包 `sandbox_id, endpoint, token = await self._provisioner.spawn(user_id)`;`repo.register(sandbox_id, user_id, endpoint, token)`。
- [ ] **Step 4: 测试过 + 全量** — `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q`,Expected: 全 PASS(调用 `get_endpoint_for_user` 的既有 turn 测试会因返回类型变化而需 Task SI-6 配合——本 task 仅到此,turn 路径在 SI-6 改;若 turn 测试此刻红,SI-6 修复)。
- [ ] **Step 5: 提交** `feat(backend): sandbox auth token through provisioner/registry/manager (SandboxConn)`

## Task SI-6: turn 透传 + worker metadata + 隔离测试改造(C②-d)

**Files:** Modify `turn/assemble.py`、`api/turn.py`、worker `server.py`、worker `sandbox_executor.py`;Modify `services/backend/tests/test_docker_sandbox_isolation.py`;Test worker `tests/test_sandbox_executor.py`(既有,补用例)

- [ ] **Step 1: 失败测试**(worker `tests/test_sandbox_executor.py` 追加;用 fake stub 捕获 metadata):

```python
async def test_exec_tool_sends_token_metadata():
    captured = {}

    class _Stub:
        async def ExecTool(self, req, metadata=None):
            captured["md"] = metadata
            from agent_cloud.v1 import sandbox_pb2
            return sandbox_pb2.ExecToolResponse(content="ok", is_error=False)

    from agent_cloud_worker.sandbox_executor import SandboxToolExecutor
    from agent_cloud_common import ToolCall

    ex = SandboxToolExecutor(channel=None, work_subdir=".", token="sekret")
    ex._stub = _Stub()  # 直接注入,绕过 channel
    await ex.execute(ToolCall(id="c1", name="bash", arguments={"command": "ls"}))
    assert ("x-sandbox-token", "sekret") in (captured["md"] or ())
```

- [ ] **Step 2: 确认失败** — `cd services/worker && uv run pytest tests/test_sandbox_executor.py -q`,Expected: `SandboxToolExecutor` 无 token 参数 / 不带 metadata。
- [ ] **Step 3: 实现**:
  - worker `sandbox_executor.py`:`__init__` 加 `token: str = ""`;存 `self._md = (("x-sandbox-token", token),) if token else None`;`ExecTool` 调用改 `await self._stub.ExecTool(req, metadata=self._md)`。
  - worker `server.py`:建 channel 处 `SandboxToolExecutor(channel, request.work_subdir, list(request.agent.enabled_tools), token=request.sandbox_token)`。
  - `turn/assemble.py`:`build_run_turn_request` 加参数 `sandbox_token: str = ""`;`RunTurnRequest(...)` 加 `sandbox_token=sandbox_token`。
  - `api/turn.py`:两处 `sandbox_endpoint = await manager.get_endpoint_for_user(...)` 改为 `conn = await manager.get_endpoint_for_user(...)`;后续 `sandbox_endpoint=conn.endpoint` 处一并传 `sandbox_token=conn.token`(一元 79/97/132、流式 235/250/273 各处;`_reassemble` 闭包同样带上 conn.token——闭包内重取或闭包捕获 conn）。
  - `test_docker_sandbox_isolation.py`:`_exec(endpoint, ...)` 改为 `_exec(endpoint, token, ...)`,带 `metadata=(("x-sandbox-token", token),)`;`spawn` 返回三元组,各 `sid, ep = await prov.spawn(...)` 改 `sid, ep, tok = await prov.spawn(...)`;调用带 tok。新增 `test_sandbox_rejects_missing_token`:不带 token 直连 → UNAUTHENTICATED。
- [ ] **Step 4: 测试过** — `cd services/worker && uv run pytest -q`;`cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q` 全 PASS;本地 `uv run pytest tests/test_docker_sandbox_isolation.py -q`(有镜像,需先重建带 token 的镜像——镜像本身无需改,token 经 env 注入)PASS。
- [ ] **Step 5: 提交** `feat(backend/worker): thread sandbox token end-to-end; reject unauthenticated ExecTool`

## Task SI-7: per-sandbox 网络(B)

**Files:** Modify `sandbox/docker_provisioner.py`、`config.py`、`deploy/compose.yml`;Test `services/backend/tests/test_docker_sandbox_isolation.py`

- [ ] **Step 1: 失败测试**(test_docker_sandbox_isolation.py 追加;network 模式 + 临时 worker 容器模拟):

```python
async def test_per_sandbox_network_isolates_tenants(tmp_path, docker_client):
    # network 模式:两个沙箱各在专属网络,A 连不到 B 的容器名
    import uuid
    prov = DockerProvisioner(
        host_root=str(tmp_path), image="agent-cloud-sandbox:latest",
        network_mode="network", worker_container=_throwaway_worker(docker_client),
    )
    a, b = uuid.uuid4(), uuid.uuid4()
    sid_a, ep_a, tok_a = await prov.spawn(a)
    sid_b, ep_b, tok_b = await prov.spawn(b)
    try:
        name_b = ep_b.split(":")[0]
        out, _ = await _exec(ep_a, tok_a, "bash",
                             {"command": f"timeout 3 wget -qO- http://{name_b}:50051 || echo UNREACHABLE"})
        assert "UNREACHABLE" in out  # 跨网络不可达
    finally:
        await prov.stop(sid_a); await prov.stop(sid_b)
    # 网络被清理
    assert not docker_client.networks.list(names=[f"acsbx-net-{sid_a}"])
```

(`_throwaway_worker` / `docker_client` fixture:起一个长命令 alpine 容器当"worker"靠点让 connect 有对象;细节实现时补。)

- [ ] **Step 2: 确认失败** — 本地 `cd services/backend && uv run pytest tests/test_docker_sandbox_isolation.py::test_per_sandbox_network_isolates_tenants -q`,Expected: `DockerProvisioner` 无 `worker_container` 参数 / 沙箱仍同网络可达。
- [ ] **Step 3: 实现** — `docker_provisioner.py`:
  - `__init__` 加 `worker_container: str = ""`;`network` 模式下为空 → spawn 时 fail-loud(`raise ValueError("network mode requires sandbox_worker_container")`)。
  - `spawn` 的 `network` 分支改为:`net_name = f"acsbx-net-{sandbox_id}"`;`client.networks.create(net_name, driver="bridge", labels={"managed-by": _LABEL})`;`kwargs["network"] = net_name`;容器起来后 `client.networks.get(net_name).connect(self._worker_container)`;`endpoint = f"{name}:{_SANDBOX_PORT}"`。失败清理:连同网络一起删。
  - `stop`:remove 容器后 `net = client.networks.get(f"acsbx-net-{sandbox_id}")`;`net.disconnect(self._worker_container)`(吞 NotFound/APIError);`net.remove()`(吞)。
  - `stop_all`:清沙箱容器后,`for n in client.networks.list(filters={"label": f"managed-by={_LABEL}"}): try disconnect all + remove`。
  - `config.py`:加 `sandbox_worker_container: str = ""`;`deps.py` 造 DockerProvisioner 处传入。
  - `compose.yml`:`worker` 服务加 `container_name: agent-cloud-worker`;`backend.environment` 加 `AGENT_CLOUD_SANDBOX_WORKER_CONTAINER: agent-cloud-worker`。
- [ ] **Step 4: 测试过** — 本地 docker 测试全过;`-m "not docker"` 全量不回归。
- [ ] **Step 5: 提交** `feat(backend): per-sandbox docker network — tenants and db unreachable from a sandbox`

## Task SI-8: 回归 + Fable 5 审查 + PR

- [ ] 全量:common / worker / backend(`-m "not docker"`)/ ruff / 本地 docker 测试(SI-6+SI-7)全绿。
- [ ] Fable 5 对抗审查(diff 内联)重点:token 向后兼容(空=开放)的边界与误开放风险、拦截器 metadata 解析(大小写/重复 key)、SandboxConn 三处 return 与 race 路径一致性、provisioner 网络生命周期的失败清理(半建容器/孤儿网络)、worker_container fail-loud、migration server_default、turn `_reassemble` 闭包的 token、隔离测试是否真经过拦截器路径。修复后重跑。
- [ ] 推分支 → PR(`fix: sandbox cross-tenant isolation — token auth + per-sandbox network + strong db password`)→ CI 绿(docker 测试 CI 跳,说明本地已验)→ 等合并指令。
