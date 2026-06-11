# 沙箱跨租户隔离修复(B + C)设计

**日期:** 2026-06-11
**状态:** 设计已批准

## 背景与威胁

生产 `network` 模式下所有沙箱 + db/worker/backend 同在 `agent-cloud-net`,docker 自定义 bridge 默认容器间互通。被攻陷的沙箱可:① 直连邻居沙箱 `:50051`(gRPC `ExecTool` 零认证 `add_insecure_port`)→ 在邻居租户沙箱里执行任意命令、读其 `/workspace`;② 直连 `db:5432`(弱密码 `postgres:postgres`)→ 全库读写。这是跨租户穿透。完整威胁模型与方案另出**面向人读的安全文档** `docs/security/sandbox-isolation.md`(见 §D)。

## 范围

四块,按"安全杠杆 / 平台可移植性"排序实现:**D 文档 → C① 强密码 → C② token 鉴权(跨平台永久)→ B per-sandbox 网络(docker 单机,封装在 DockerProvisioner)**。

---

### D. 安全文档(`docs/security/sandbox-isolation.md`)

刻意分两层,便于 k8s 迁移时只换实现章:
- **威胁模型 / 隔离目标(永久)**:多租户 + agent 自主执行 + prompt-injection 攻陷源;信任边界(LLM key 仅 worker、沙箱最不可信);跨租户可达性表(现状漏洞);隔离目标(沙箱间互不可达、沙箱够不到 db/backend、沙箱出公网受控、"连到端口 ≠ 能执行")。
- **实现(分平台)**:docker 单机 = 本次的 B+C;k8s 未来 = NetworkPolicy(替代 B)+ Secret(承载 C①)+ token(C② 原样复用)+ 起 Pod 经 k8s API、workspace 走 RWX PVC(更根本的迁移瓶颈,正交、不在本次范围)。

### C①. postgres 强密码(compose/.env,零 Python)

- `deploy/compose.yml`:`db.environment.POSTGRES_PASSWORD: ${AGENT_CLOUD_DB_PASSWORD:?set AGENT_CLOUD_DB_PASSWORD in .env}`(`:?` 缺失即 fail-loud,不静默回退弱密码);`backend.environment.AGENT_CLOUD_DATABASE_URL` 用同一变量拼接。
- `.env.example`(若无则建)注明 `AGENT_CLOUD_DB_PASSWORD=` 需填强随机值;`deploy/README.md` 补一句。
- 既有部署迁移提示写进安全文档(改密码需同时改 db 卷里的角色密码或重建 db——文档给步骤)。

### C②. 沙箱 gRPC token 鉴权(跨平台永久;proto + 五处接线)

**机制**:每沙箱一个随机 token,沙箱 server 校验调用方 metadata,worker 调用时带上。"连到端口 ≠ 能执行"。

- **proto**(`worker.proto`):`RunTurnRequest` 加 `string sandbox_token = 11;`,重新生成。
- **沙箱 server**(`services/sandbox`):
  - `__main__` 读 `AGENT_CLOUD_SANDBOX_TOKEN`(env,可空);
  - `create_server(base_workdir, host, port, token="")`:`token` 非空时装一个 `grpc.aio.ServerInterceptor` 校验 metadata `x-sandbox-token == token`,不符 → abort `UNAUTHENTICATED`;**空 token = 不校验**(向后兼容 inprocess/CI、旧镜像)。
- **SandboxProvisioner Protocol**:`spawn` 返回三元组 `(sandbox_id, endpoint, token)`。
  - `DockerProvisioner`:**始终**生成 `secrets.token_urlsafe(32)`,注入容器 env `AGENT_CLOUD_SANDBOX_TOKEN`,返回之(docker 沙箱恒有 token)。
  - `InProcessProvisioner`:返回 `token=""`(CI/dev 无隔离需求;其 server 不配 token → 放行)。
- **registry 表**:`sandbox_registry` 加 `auth_token: str`(`default=""`,nullable=False)+ alembic migration;`register(sandbox_id, user_id, endpoint, token)` 写入;复用已有沙箱(`get_active_for_user`)时连同 token 取回。
- **manager**:`get_endpoint_for_user` 返回 `(endpoint, token)`(小 dataclass `SandboxConn`,避免裸 tuple 扩散);两条 spawn/复用路径都带上。
- **turn 路径**(`turn/assemble.build_run_turn_request` + 一元 `api/turn.py` + 流式 `api/turn.py`/`runner`):`sandbox_token` 一路透传进 `RunTurnRequest`。
- **worker**(`server.py` 建 channel 处 + `sandbox_executor.py`):`SandboxToolExecutor` 增 `token` 参数;`ExecTool` 调用带 `metadata=(("x-sandbox-token", token),)`(token 空则不带)。

### B. per-sandbox 网络(仅 `DockerProvisioner`,`network` 模式;封装不外溢)

**只改 `DockerProvisioner` 内部 + compose 配置**,不碰 Protocol 签名(endpoint 仍为 `容器名:port`)、不碰 manager/proto/db。`publish` 模式(dev 单用户)保持现状不做 per-network。

- **spawn**(`network` 模式):
  1. `docker network create acsbx-net-<sandbox_id>`(普通 bridge,可出公网 NAT;label `managed-by=agent-cloud`);
  2. 沙箱容器接入该专属网络(不再接 `agent-cloud-net`)→ 沙箱物理上不在 db/backend 的网络;
  3. `network.connect(<worker_container>, ...)`:把 worker 容器接进该网络(worker 是唯一需连沙箱的)。worker 容器名来自新配置 `sandbox_worker_container`(`network` 模式必填,空则 fail-loud)。
- **stop**:remove 沙箱容器 → `network.disconnect(<worker_container>)` → `network.remove(acsbx-net-<id>)`(best-effort,吞 NotFound)。
- **stop_all / 孤儿清理**:按 label 清沙箱容器后,清理 `acsbx-net-*` 残留网络。
- **配置**:`config.py` 加 `sandbox_worker_container: str = ""`;compose `backend.environment` 加 `AGENT_CLOUD_SANDBOX_WORKER_CONTAINER`(worker 服务固定 `container_name`)。
- **残留风险**(文档标注):worker 与沙箱在 per-net 内双向可达,沙箱仍能连 `worker:50052`——但 worker `RunTurn` 需 backend 注入的 api_key,沙箱自带不了 key,至多 DoS;后续可给 worker 也加 token。沙箱**已够不到** db/backend/邻居沙箱(本次目标达成)。

## 非目标(YAGNI)

- 不做 egress 出网 allowlist(独立加固项,roadmap 在册);不给 worker gRPC 加 token(残留项,文档标注);不做 k8s provisioner(未来);不动 DooD / bind-mount workspace(k8s 迁移的根本瓶颈,正交)。

## 测试

- **C① 强密码**:无自动化(compose 配置);文档给 fail-loud 验证步骤。
- **C② token**(`@pytest.mark.docker` + 单测):
  - 沙箱 server interceptor 单测:配 token 时缺/错 metadata → `UNAUTHENTICATED`,正确 token → 放行;空 token(未配)→ 放行(向后兼容)。
  - `test_docker_sandbox_isolation.py` 改造:`_exec` 从 spawn 返回的 token 取出并带进 metadata(更真实——本就模拟 worker);新增「不带 token 直连 → UNAUTHENTICATED」。
  - worker `sandbox_executor` 单测:`token` 非空时 `ExecTool` 调用携带 `x-sandbox-token` metadata(fake stub 断言)。
  - inprocess 全链路既有 e2e 不回归(空 token 放行)。
- **B 网络隔离**(`@pytest.mark.docker`):`network` 模式起两个沙箱(各自专属网),从沙箱 A `bash` 尝试连沙箱 B 的容器名/网段 → 不可达;沙箱 A 尝试连一个"伪 db"容器(挂在 `agent-cloud-net`)→ 不可达;`stop` 后 `acsbx-net-<id>` 网络被清理(`network ls` 不剩)。worker-connect 用一个 throwaway 容器模拟 worker 角色验证接入后可达。
- 既有隔离测试(跨用户读不到、pip 依赖跨重建)随 token 改造后仍绿。
