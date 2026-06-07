# Docker 沙箱 Provisioner 设计(spec · 第一版)

> 状态:方向已与用户确认(2026-06-07)。目标=给沙箱真正的文件系统隔离,堵住「bash 用绝对路径越权读其他用户文件」的洞。范围=`DockerProvisioner`(开发机 + 裸机/compose),k8s 留接口不实现。

## 1. 背景与问题

当前 `InProcessProvisioner` 直接在宿主机上跑工具:`read_file`/`write_file` 受 `_resolve_within` 限制在 workdir 内,但 **`bash` 不受限**——`subprocess.run(cmd, shell=True, cwd=workdir)`,命令里写绝对路径(`cat /private/tmp/agent-cloud-sandboxes/<别的用户>/...`)或 `cd ..` 就能读宿主机上任何该进程有权限的文件。实测可跨用户读取。

纯命令层过滤不可靠(易绕过)。**唯一可靠的修法是 OS 级隔离**:把沙箱放进容器,容器内只挂载该用户自己的工作空间,宿主机其它路径在容器里**根本不存在**。

## 2. 目标 / 非目标

**目标**
- 每个沙箱跑在独立容器里,容器内**只能看到该用户的工作空间**(挂在 `/workspace`)。
- 容器是「可丢弃算力」:崩了自动重建并挂回同一持久卷,文件不丢。
- 沿用现有 `SandboxManager` / registry / 健康探活 / `reap_idle`,改动集中在新增一个 provisioner。
- 同一实现覆盖**本地开发**和**裸机/docker-compose** 两种部署。
- Protocol 保持 k8s 友好,将来加 `KubernetesProvisioner` 不改核心。

**非目标(本版不做)**
- `KubernetesProvisioner`(留接口)。
- gVisor/microVM、cgroups 精细配额(留加固项,给出钩子)。
- 跨主机调度、热容器池(A3)、自动扩缩容。

## 3. 架构总览

```
backend(SandboxManager)
  └─ SandboxProvisioner (Protocol)  ← 已存在的抽象口子
       ├─ InProcessProvisioner   (dev 默认;无隔离;单测快)
       ├─ DockerProvisioner      (本版新增;容器隔离)
       └─ KubernetesProvisioner  (将来;k8s API 建 Pod)
```

`SandboxManager.get_endpoint_for_user` 已有的逻辑全部复用:registry「每用户一个活跃沙箱」+ 健康探活(死则 `mark_dead` 重建)+ `reap_idle`(空闲回收)。provisioner 只需实现 `spawn(user_id) -> (sandbox_id, endpoint)`、`stop(sandbox_id)`、`stop_all()`。

**用配置选 provisioner**:`AGENT_CLOUD_SANDBOX_PROVISIONER = inprocess | docker`(默认 `inprocess`,保持单测/CI 不依赖 Docker)。

## 4. 容器生命周期(A1:每用户常驻 + 回收)

- 用户**首个回合**:`get_endpoint_for_user` 在 registry 找不到活跃沙箱 → `DockerProvisioner.spawn(user_id)` → `docker run -d` 起容器 → 登记 endpoint。
- 之后该用户**所有 session/回合复用**(无冷启动)。
- 空闲超 TTL:`reap_idle` → `DockerProvisioner.stop(sandbox_id)` → `docker stop`(算力释放,**卷保留**)。下次用再起。
- 容器崩溃:下个回合健康探活失败 → `mark_dead` → 重建新容器挂回同卷(自愈)。
- backend 重启:容器是 detached,**仍在运行**;探活存活 → 直接复用(比进程内沙箱更稳)。

稳态容器数 ≈ 活跃用户数 + 一小段 TTL 尾巴,**随并发扩,不随注册用户数扩**(5 万用户/500 活跃 ≈ 500 容器;空闲的不存在,文件在卷上)。

### 4.1 spawn / reap 时机(明确)

- **spawn = 懒创建,在回合开始**(`get_endpoint_for_user`)按需:仅当该用户「无健康活跃沙箱」才建(首回合 / 被 reap 后再用 / 沙箱死了重建),否则复用并 `touch` 续期。建 user/agent/session、光浏览都**不**建沙箱。
- **reap**:停掉「距上次回合开始超 `idle_ttl`(默认 1800s=30min)」的沙箱。活跃用户每回合 `touch` 续期 → 永不被收;回收的是容器、**卷保留**;回头再用冷启动一个新容器挂回同卷。
- ⚠️ **必须接后台 reaper(本方案新增)**:现有 `reap_idle()` **没有任何调用方**——不接的话容器只建不收、越积越多。在 FastAPI lifespan 起后台任务,每 `reap_interval`(默认 120s)调 `reap_idle()`,关停时取消。
- reaper **跳过 session 仍 `running` 的沙箱**(`last_used_at` 只在回合开始 touch,避免长回合被中途回收);`idle_ttl` 也须 > 最长回合时长。
- **冷启动隐藏**:回合开始时**并行**预热容器(与首个 LLM 思考重叠)——模型要先思考几秒才会调第一个工具,这窗口正好让容器 ready;worker 首个工具调用对沙箱连接做**短重试**兜底。稳态(复用)0 冷启动;冷启动只在首回合 / 被回收后出现一次 ~1–3s,且基本被"思考"遮掉。

## 5. 路径 / 卷模型(关键)

- **持久卷(宿主机)**:`<SANDBOX_HOST_ROOT>/<user_id>/workspace/`。这就是用户级共享工作空间(同用户所有 agent/session 共用),持久、跨容器重建稳定。
- **挂载**:把该目录挂进沙箱容器的 `/workspace`(`-v <host>/<user_id>/workspace:/workspace:rw`)。
- **沙箱服务根**:容器内 `agent_cloud_sandbox` 服务以 `base_workdir=/workspace` 启动。
- **work_subdir 退化**:用户级共享后 `session.work_subdir="workspace"` 本就指向该目录;容器化后该目录已是 `/workspace`,故发往沙箱的请求用 `work_subdir="."`(`_resolve_within(/workspace, ".")=/workspace`,通过非空校验),**不再二次嵌套**。
  - 实现:`DockerProvisioner` 路径下,assemble 时把传给 worker 的 `work_subdir` 置为 `"."`(`inprocess` 仍用 `"workspace"`,保持现状)。由 provisioner 类型决定,后续在接线处统一。

> 隔离点:容器里**只挂了**这一个用户的 `/workspace`,宿主机的 `/private/tmp/agent-cloud-sandboxes/<别的用户>/` 在容器内不存在 → `cat /别人/...` 必然失败。

## 6. 网络(开发 vs 生产不同)

是 **worker** 连沙箱(worker→sandbox 信任边界)。两种模式,provisioner 按配置 `AGENT_CLOUD_SANDBOX_DOCKER_NETWORK_MODE` 切换:

- **dev(worker 跑在宿主机,dev_up.sh)**:容器**发布端口**到宿主 `-p 0:50051`(取随机宿主端口),endpoint = `127.0.0.1:<host_port>`,worker 在宿主连 localhost。
- **prod(worker 也在容器、同一 docker 网络)**:容器**不发布端口**,加入共享网络 `agent-cloud-net`,endpoint = `<容器名>:50051`(Docker 内置 DNS 解析),worker 同网按名连。

## 7. 部署形态

| 形态 | backend 在哪 | 怎么连 daemon | 卷路径 | 网络 |
|---|---|---|---|---|
| **本地开发** | 宿主机(uvicorn) | 直接用本机 docker(`docker.from_env()`),**无需挂 socket** | backend 在宿主,路径即宿主路径,直传 | 发布端口,localhost |
| **裸机/compose** | 容器内 | 挂宿主 `/var/run/docker.sock`(DooD) | 需 `SANDBOX_HOST_ROOT`=**宿主**路径(坑①) | 共享 `agent-cloud-net`,按容器名 |
| k8s(将来) | Pod | 不碰 docker,调 k8s API | PVC | Pod IP / Service |

**坑①(DooD 卷路径)**:daemon 在宿主,`-v <path>:/workspace` 的 `<path>` 在**宿主**解析。backend 容器内看到的挂载点 ≠ 宿主路径,故必须单独配 `SANDBOX_HOST_ROOT`(宿主上 workspace 根),拼 `-v` 时用它。开发机 backend 在宿主,该值=`AGENT_CLOUD_SANDBOX_BASE_ROOT`,无差异。

## 8. 沙箱镜像

`deploy/sandbox.Dockerfile`:基于 `python:3.13-slim`,装 `agent_cloud_sandbox` 包(+ `agent_cloud_common` 依赖),`CMD` 启动 gRPC 沙箱服务监听 `0.0.0.0:50051`、`base_workdir=/workspace`。镜像名 `agent-cloud-sandbox:latest`(配置可改)。多机部署推到 registry。`dev_up.sh` 增加一步 `docker build`。**用户想长期具备的系统工具(apt 包)写进这个 Dockerfile**(所有用户共用、可复现)。

## 8.1 依赖持久化(目标:尽量保留用户依赖)

容器根 fs 是临时的、只有 `/workspace` 卷持久,所以策略是**把依赖尽量引到 `/workspace`**:

1. **语言级依赖 → 路由进 `/workspace` → 跨容器重建永久保留**(覆盖绝大多数场景)。镜像内设环境变量,把各工具的 home/缓存/安装前缀都指向卷:
   - `HOME=/workspace/.home`(→ `~/.local`、`~/.cache`、pip `--user` 等)
   - Python:`PYTHONUSERBASE=/workspace/.home/.local` + `PIP_USER=1` → `pip install X` 默认装 `--user` 进卷,**免去建 venv 的冷启动开销**(建 venv 要多 2–5s)。需要隔离环境的项目仍可自建 `/workspace/.venv`。
   - Node:`NPM_CONFIG_PREFIX=/workspace/.npm-global`(+ PATH)、cache 在 HOME 下 → 本地与 `-g` 安装都持久
   - `XDG_DATA_HOME`/`XDG_CACHE_HOME`、`CARGO_HOME`、`GOPATH` 等同理指向 `/workspace/.home`
   - 这些 `.` 开头目录在卷里隐藏,不干扰用户可见的工作区根。
2. **系统级(apt)依赖 → 容器热期内保留**:根 fs **可写**(见 §9),配合 A1 常驻容器,apt 装的系统包在容器被 reap/崩溃前一直在(跨回合、跨 session)。**冷重建后回到镜像初始态**(系统包丢失)。
3. **让系统包也扛过冷重建**:写进沙箱镜像 Dockerfile;或(后续增强)用户在 `/workspace` 放 `requirements.txt`/`apt-packages.txt`,spawn 时自动重装(声明式、可复现)。

> 不做 per-user `docker commit` 快照(镜像爆炸、慢、乱)。

## 9. 安全

**沙箱容器(跑不可信代码)加固**(`docker run` 参数,配置可调):
- `cap_drop=["ALL"]`、`security_opt=["no-new-privileges"]`。
- 根文件系统**可写**(让 apt/系统级安装在容器热期内可用,配合 §8.1 的依赖保留目标)。**跨用户隔离不依赖只读根 fs**——它来自「每用户独立容器 + 只挂自己的 `/workspace`」,根 fs 是否只读不影响别人的文件可见性。更严格场景可改 `read_only=True`(代价:apt 等系统安装直接失败)。`/tmp` 用 tmpfs。
- 资源上限:`mem_limit`、`nano_cpus`、`pids_limit`、磁盘配额(防写满)。
- 网络出网:**默认允许出网**(`pip`/`npm` 装依赖需要,契合 §8.1 保留依赖的目标);可按 `ALLOW_NET=false` 收紧,或后续接出网代理/域名 allowlist(放行 PyPI/npm registry,挡其余)。
- **绝不**给沙箱挂 docker socket。
- 加固钩子:`runtime`(配 `runsc` 上 gVisor)预留为配置。

**socket 本身(仅 compose 形态)**:挂 socket 给 backend = 宿主 root。生产建议二选一:
- `docker-socket-proxy` 白名单只放行 `containers` 的 create/start/stop;或
- 独立最小权限的 provisioner 小服务持有 socket,backend 调其窄接口。
开发机(backend 在宿主、本就是你自己)直接用本机 docker,无此风险。

## 10. 配置项(新增)

| env | 默认 | 说明 |
|---|---|---|
| `AGENT_CLOUD_SANDBOX_PROVISIONER` | `inprocess` | `inprocess` / `docker` |
| `AGENT_CLOUD_SANDBOX_HOST_ROOT` | =`SANDBOX_BASE_ROOT` | DooD 下宿主 workspace 根(坑①) |
| `AGENT_CLOUD_SANDBOX_IMAGE` | `agent-cloud-sandbox:latest` | 沙箱镜像 |
| `AGENT_CLOUD_SANDBOX_DOCKER_NETWORK_MODE` | `publish` | `publish`(dev)/ `network`(prod) |
| `AGENT_CLOUD_SANDBOX_DOCKER_NETWORK` | `agent-cloud-net` | network 模式下的网络名 |
| `AGENT_CLOUD_SANDBOX_MEM_LIMIT` / `_CPUS` / `_PIDS` | 合理默认 | 资源上限 |
| `AGENT_CLOUD_SANDBOX_IDLE_TTL_SECONDS` | `1800` | 空闲多久回收(自上次回合开始) |
| `AGENT_CLOUD_SANDBOX_REAP_INTERVAL_SECONDS` | `120` | 后台 reaper 轮询间隔 |
| `AGENT_CLOUD_SANDBOX_ALLOW_NET` | `true` | 沙箱是否可出网(装依赖需要;可关) |

## 11. 后端改动清单

- 新增 `services/backend/.../sandbox/docker_provisioner.py`:`DockerProvisioner`(用 `docker` SDK),实现 `spawn/stop/stop_all`,处理端口/网络/卷/加固;给容器命名 `acsbx-<user_id>` 便于排障与孤儿清理。
- `sandbox/deps.py`:按 `AGENT_CLOUD_SANDBOX_PROVISIONER` 选 `InProcess` 或 `Docker`(后者注入 host_root/image/network/limits)。
- assemble/turn 接线:provisioner=docker 时 `work_subdir="."`(见 §5)。
- `config.py`:新增 §10 配置项。
- `deploy/sandbox.Dockerfile` + `scripts/dev_up.sh` 增加构建沙箱镜像 + 设 `AGENT_CLOUD_SANDBOX_PROVISIONER=docker`(开发默认仍可切回 inprocess)。
- `main.py` lifespan:起后台 reaper 任务(每 `REAP_INTERVAL_SECONDS` 调 `manager.reap_idle()`),关停时取消——**接上目前没有调用方的 `reap_idle`**。
- `reap_idle` 跳过 session 仍 `running` 的沙箱(查 session 状态),避免长回合被中途回收。
- 冷启动隐藏:回合开始**并行**预热沙箱(不阻塞首个 thinking 流);worker 首个工具调用对沙箱连接做短重试。
- 依赖:backend 加 `docker`(Python SDK)。

## 12. 测试策略

- **单元**:`DockerProvisioner` 用**假 docker client** 验证 `spawn` 组装的参数(镜像、卷=host_root/<uid>/workspace→/workspace、加固项、网络/端口、命名),`stop` 幂等。
- **隔离集成测试(核心,需真 Docker,默认跳过/打标记)**:起两个用户的沙箱,用户 A 写 `secret.txt`;用户 B 的沙箱里 `bash cat <A 的绝对路径>` **必须失败**(文件在 B 容器内不存在),且 `bash ls /` 看不到别的用户目录 → 证明越权被堵。
- **e2e**:沿用现有 turn e2e,但 provisioner=docker;断言文件落在 `<host_root>/<uid>/workspace/`,跨用户隔离。
- 现有套件继续用 `inprocess`(不引入 Docker 依赖,CI 快)。

## 13. 风险 / 取舍

- **冷启动**:首回合/重建/空闲后约 1–2s 起容器,相对 LLM 回合(10–30s)可忽略;TTL 调长可减少。
- **socket 安全**:compose 形态需 proxy/小服务收敛权限(§9);开发机无此问题。
- **镜像体积/构建**:首次 `docker build` 有成本;`dev_up.sh` 自动化。
- **work_subdir 双语义**:inprocess 用 `"workspace"`、docker 用 `"."`——在接线处按 provisioner 区分,需写清避免混淆。
- **出网策略**:默认禁网最安全,但会断 pip/联网工具;用 `ALLOW_NET` 显式开。
- in-process 保留为默认,确保单测/CI 不依赖 Docker。

## 14. 验收

- 配 `AGENT_CLOUD_SANDBOX_PROVISIONER=docker` 跑 dev_up.sh:发消息能写文件、`python3 x.py` 能跑(相对路径)。
- 用户 A 的会话写的文件,用户 A 的另一会话能读(用户级共享仍成立)。
- **用户 B 的沙箱无法读到用户 A 的文件**(bash 绝对路径/`ls /` 都看不到)——越权洞关闭。
- 用户 `pip install <包>`(或 `npm install`)后,**杀掉容器触发冷重建**,再 `python -c "import <包>"`(或用该 npm 包)**仍成功**——语言级依赖跨重建保留(§8.1)。
- backend 重启后沙箱容器仍在、回合正常;空闲后容器被 reap。
```
