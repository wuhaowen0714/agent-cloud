# 沙箱隔离与跨租户安全

本文件分两层:**威胁模型 / 隔离目标**(与编排平台无关,长期不变)与**实现**(随部署形态变化:当前 docker 单机 / 未来 k8s)。迁移到 k8s 时,只需重写「实现」一章,威胁模型与目标不动。

---

## 1. 威胁模型(永久)

**系统形态**:多租户 agent 云。用户的 agent 在隔离沙箱里自主执行工具(bash / 读写文件 / curl / git)。沙箱是**最不可信**的执行单元——它跑的是 LLM 生成的、可被 prompt injection 操纵的代码。

**信任边界**(由内到外的信任递减):

| 层 | 持有 | 信任 |
|---|---|---|
| backend | DB 访问、docker 控制、鉴权 | 最高 |
| worker | LLM API key | 高(key 绝不下放沙箱) |
| sandbox | 用户自己的 workspace | **最低(假定可被攻陷)** |

**攻陷源**:用户让 agent 处理的不可信内容(网页、文件、技能 SKILL.md、第三方 API 响应)可携带注入指令,诱导 agent 在沙箱里执行攻击者的命令。**我们假定任一沙箱内的代码都可能是敌对的**,隔离不能依赖"agent 不会这么做"。

## 2. 现状漏洞(本次修复前)

生产 `network` 模式下,所有沙箱 + db + worker + backend 同在一个 docker bridge 网络 `agent-cloud-net`。docker 自定义 bridge 默认容器间互通(ICC=true)+ 容器名 DNS。一个被攻陷的沙箱可横向移动:

| 从沙箱出发 → 目标 | 可达性 | 后果 |
|---|---|---|
| 邻居沙箱 `:50051` | 同网络可达 | 沙箱 gRPC `ExecTool` **零认证**(`add_insecure_port`)→ 在邻居租户沙箱里执行任意命令、读其 `/workspace`。容器名 uuid 难猜,但扫同网段 50051 端口即可枚举所有沙箱 |
| `db:5432` | DNS 名 `db` 直达 | postgres **弱密码** `postgres:postgres`(compose 硬编码)→ 全库读写:所有租户的消息、会话、凭据密文 |
| `worker:50052` | 可达 | 消耗 LLM 额度 / DoS |
| `backend:8000` | 可达 | 内部 API 暴露面增大 |

前两行最致命:**无需任何凭据**即穿透租户隔离。根因是隔离设计当初只覆盖了**文件层**(每沙箱只 bind 自己的 workspace)与**内核层**(`cap_drop ALL` + `no-new-privileges`),网络层是已知缺口。

## 3. 隔离目标(永久)

1. **沙箱间互不可达**:沙箱 A 在网络层够不到沙箱 B。
2. **沙箱够不到控制面**:沙箱够不到 db / backend。
3. **连到端口 ≠ 能执行**:即便网络隔离被绕过,无有效凭据也调不动沙箱的 `ExecTool`(纵深防御)。
4. **出公网受控**:沙箱能联网(curl/git 等需要),但出网应可收紧为 allowlist(防数据外泄 / 内网跳板)。
5. **凭据不裸奔**:控制面凭据(db 密码)非弱默认值。

## 4. 实现

### 4.1 当前:docker 单机(本次 B + C)

- **目标 3(token 鉴权)** — 跨平台、永久保留:
  - 每沙箱一个随机 token(`secrets.token_urlsafe(32)`),`DockerProvisioner` 经容器 env `AGENT_CLOUD_SANDBOX_TOKEN` 注入,存入 `sandbox_registry.auth_token`。
  - 沙箱 gRPC server 装拦截器:校验调用方 metadata `x-sandbox-token`,不符 → `UNAUTHENTICATED`。**token 为空则不校验**(向后兼容 inprocess/CI/旧镜像)。
  - worker 调 `ExecTool` 时带该 metadata(token 经 `RunTurnRequest.sandbox_token` 由 backend 注入)。
  - 效果:邻居沙箱即便连到 `:50051`,无对方 token 也执行不了任何工具。
- **目标 1 + 2(per-sandbox 网络)** — docker 单机实现:
  - `network` 模式下,每个沙箱起在**专属** docker 网络 `acsbx-net-<id>`,不再接入 `agent-cloud-net`。
  - 沙箱因此物理上不在 db/backend/邻居沙箱的网络 → 够不到它们。
  - worker(唯一需要连沙箱的)由 backend 在 spawn 时动态 `network connect` 进该专属网络;stop 时 disconnect + remove 网络。
  - `publish` 模式(dev 单用户)保持现状不做 per-network。
- **目标 5(强密码)**:`POSTGRES_PASSWORD` 与 backend 的 `DATABASE_URL` 从 `deploy/.env` 的 `AGENT_CLOUD_DB_PASSWORD` 读取,compose 用 `${VAR:?}` 在缺失时 **fail-loud**(不静默回退弱默认)。

### 4.2 未来:k8s 跨机器

迁移到 k8s 时,**目标不变,实现替换**:

- **目标 1 + 2** → **NetworkPolicy**(声明式,CNI 级):给每个 sandbox pod 打 label,规则声明"不能访问其他 sandbox、不能访问 db/backend、只能出公网 + 被 worker 访问"。比 per-sandbox docker network 干净,天然跨机器。`DockerProvisioner` 的网络代码不迁移——k8s 用独立的 provisioner 实现(经既有 `SandboxProvisioner` 抽象),其网络隔离由 NetworkPolicy YAML 承担。
- **目标 3(token)** → **原样复用**:应用层鉴权与编排无关,k8s 下一行不改;且它是 NetworkPolicy **之外**的纵深防御(网络策略配错时兜底)。
- **目标 5(密码)** → **k8s Secret** 承载(概念一致,仅承载变化)。
- **正交的迁移瓶颈**(本次不涉及):起沙箱从 DooD(挂宿主 docker.sock 起兄弟容器)换成调 **k8s API 起 Pod**;workspace 从 bind-mount 宿主目录换成 **RWX PVC / 网络存储 / 对象存储拉取**(跨 node 不能共享宿主文件系统)。这两项比网络隔离更根本,但与本安全修复正交——本次的 token/文档不因将来做它们而回退。

## 5. 残留风险(已知,本次未覆盖)

- **沙箱 → worker:50052**:per-sandbox 网络内 worker 与沙箱双向可达,沙箱仍能连 worker。但 worker `RunTurn` 需 backend 注入的 LLM api_key,沙箱自带不了 → 至多 DoS。后续可给 worker gRPC 也加 token。
- **egress 出网未限制**:沙箱能出任意公网(python 一直能,curl/git 同理)。多租户下需 **egress allowlist** 防数据外泄 / 内网跳板。独立加固项,见 roadmap「限流/配额/滥用防护」。
- **token 落库明文**:`sandbox_registry.auth_token` 存明文。其防护对象是"网络层被绕过后的横向";而 db 本身已由强密码(目标 5)+ 摘网络(目标 2,沙箱够不到 db)保护。db 被打穿时攻击者已取得更高权限,token 泄露是次要的。

## 6. 运维:设置 / 变更 db 密码

- **首次部署**:在 `deploy/.env` 设 `AGENT_CLOUD_DB_PASSWORD=<强随机值>`(如 `openssl rand -base64 24`)。未设时 `docker compose up` 直接 fail-loud,不会用弱默认起库。
- **变更已有部署的密码**:db 卷里的角色密码在初始化时已固化,改 `.env` 不会自动改库内密码。需二选一:
  1. 改库内密码:`docker compose exec db psql -U postgres -c "ALTER ROLE postgres PASSWORD '<新值>';"`,再同步更新 `.env` 的 `AGENT_CLOUD_DB_PASSWORD` 并重启 backend;
  2. 重建 db 卷(**会丢数据**,仅限可弃数据的环境):`docker compose down`(**不要 `-v` 除非确认丢数据**)→ 删卷 → `up`。
