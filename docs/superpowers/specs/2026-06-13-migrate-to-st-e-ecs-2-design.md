# 迁移部署:ali-ecs → st-e-ecs-2(保留 47.94.140.245:8080 入口)

> **性质:这是一份运维 runbook,不是 TDD 功能开发。** 故不走 writing-plans 的"红绿测试"流程;本文件即执行计划。Part A(仓库改动)走常规 PR;Part B(迁移执行)是对线上服务器的有序 ops,**Phase 1 切换前会再次向用户确认**。

**目标:** 把 agent-cloud 全栈 + 全部数据从 ali-ecs(阿里云 1.6G 小机)迁到 st-e-ecs-2(32核/62G 大机),今后在 st-e-ecs-2 部署;同时**保留** `http://47.94.140.245:8080/` 这个老用户在用的入口。

**非目标:** 不改应用功能;不上 k8s / Redis;不追求零停机(数据量小,短暂停机可接受)。

---

## 1. 现状(已探测,2026-06-13)

| 项 | ali-ecs(源) | st-e-ecs-2(目标) |
|---|---|---|
| SSH | `root@47.94.140.245:22` | `sophgo@106.75.235.242:9022`(免密 sudo) |
| 提供商 / IP | 阿里云 EIP `47.94.140.245` | 另一机房,公网 `106.75.235.242`(端口受网关限制) |
| 规格 | 1.6G RAM / 40G(用 15G) | 32核 / 62G RAM / 469G(用 15G) |
| Docker | 29.1.3 + compose 插件 ✓ | 28.2.2 ✓,**但缺 `docker compose` 插件** ✗ |
| 应用栈 | db+backend+worker+web 全 Up | 无(宿主上有**他人的 nginx** 占 80/443/8359/8459,勿动;8080 空闲) |
| 公网放通端口 | 8080(阿里云安全组) | **仅 8359/8459/9022**;80/443/8080 不通 → 需新开 **18080** |
| 数据量 | pgdata 64M / objstore 424K / workspaces 754M(9 用户)≈ **820M** | — |

**关键约束:** `47.94.140.245` 是阿里云 EIP,**无法迁到非阿里云的 st-e**。保留该入口 ⇒ ali-ecs 必须留一个监听 8080 的东西(302 重定向容器,见 §2)。

---

## 2. 最终形态

```
老用户 ──GET──> 47.94.140.245:8080 (ali-ecs:仅剩 1 个 nginx 重定向容器)
                          │  302 → http://106.75.235.242:18080$request_uri(几百字节,秒回)
                          ▼ 浏览器自动跳转,之后所有流量直连 st-e
        网关公网 106.75.235.242:18080 ──转发──> st-e VM:18080
                          │
                          ▼
        st-e web(nginx) :80 ── /api 反代 ──> backend:8000  (+ worker / db / 按需沙箱)
主入口: http://106.75.235.242:18080/(跳转后地址栏即此)
```

- **st-e-ecs-2**:完整应用栈 + 全部数据;今后 deploy 都在这台。
- **ali-ecs**:停掉应用栈(容器与卷保留作回滚),只起一个 `nginx:alpine` 做 **302 重定向**(非反代)。老入口/书签永久有效,深链路径经 `$request_uri` 保留。
- **为什么重定向而非反代(实测定案)**:ali 出向仅 **3.5 Mbps**、st-e 约 **168 Mbps**(2026-06-13 实测,差 ~50 倍)。反代会把经 47.94 的全部流量封顶在 3.5 Mbps 且多用户共享;重定向后流量全走 st-e 大带宽,ali 只出重定向响应。用 302(非 301):浏览器不持久缓存,将来可随时改向/切回反代。
- 重定向模式下 ali 端无需任何 SSE/WS/缓冲透传配置(没有流量过境)。

---

## 3. 决策(已与用户确认)

1. st-e 公网端口 = **18080**(用户开通网关转发 公网18080→VM18080)。
2. 接受 **~5–10 分钟停机窗口**(Phase 1)。
3. **暂不做入站限制** → st-e:18080 同时作为直连入口对公网开放。
4. `.env` **逐字复制** ali → st-e(CREDENTIAL_KEY/AUTH_SECRET/DB_PASSWORD 必须不变,否则旧密文解不开、旧会话失效、DB 角色密码不匹配),仅追加 st-e 专属的 `AGENT_CLOUD_WEB_PORT` / `AGENT_CLOUD_SANDBOX_MEM_LIMIT`。
5. pgdata 用 **`pg_dump` 逻辑迁移**(在线一致快照,不锁 PG 版本、不碰卷内角色密码),灌入 st-e 全新初始化的 db。
6. 代码经 **裸仓库 ssh 推送**(st-e 是否能连 GitHub 不确定,此法无所谓):本机 `git push st main` → `st-e:/opt/agent-cloud/repo.git` → `/opt/agent-cloud/app`。
7. **ali 入口模式 = 302 重定向**(用户在带宽实测后选定;见 §2)。已知一次性代价:① 跳转后地址栏变为 `106.75.235.242:18080`;② 老用户需**重新登录一次**(token 在 localStorage,按源隔离,9 个用户成本可忽略);③ 迁移前已打开的旧标签页内的 `/api` 调用会因跨源 302 被 CORS 拦截 → 刷新页面即恢复(切换本就有停机窗口,旧标签页当时已断)。

---

## 4. Part A — 仓库改动(常规 PR,**全部向后兼容**,默认值即 ali 现行为)

> 这些改动合并到 main、推到两台服务器后,再执行 Part B。

### A1. `deploy/compose.yml`:两个值改为可被 .env 覆盖
- `web.ports`:`- "8080:80"` → `- "${AGENT_CLOUD_WEB_PORT:-8080}:80"`
- `backend.environment.AGENT_CLOUD_SANDBOX_MEM_LIMIT`:`256m` → `${AGENT_CLOUD_SANDBOX_MEM_LIMIT:-256m}`

ali 不设这两个变量 → 仍是 8080 / 256m(零变化);st-e 在 .env 设 `18080` / `2g`。

### A2. 新增 `deploy/ali-entry/`(ali 入口重定向,迁后用)
- `deploy/ali-entry/nginx.conf`:
  ```nginx
  # ali 入口:47.94.140.245:8080 → 302 跳 st-e 主入口(带宽 3.5Mbps vs 168Mbps,流量不过境)
  server {
    listen 80;
    location / {
      return 302 http://106.75.235.242:18080$request_uri;
    }
  }
  ```
  文件内附**注释掉的反代变体**(proxy_pass + Upgrade/Connection + `proxy_buffering off` + 长超时 + `client_max_body_size 100m`),想切回反代模式时取消注释、`docker compose restart` 即可。
- `deploy/ali-entry/compose.yml`:`name: agent-cloud-entry`,服务 `entry`(`nginx:alpine`,`ports: ["8080:80"]`,挂载 nginx.conf 只读,`restart: unless-stopped`)。

### A3. 文档
- `deploy/README.md`:加"双机拓扑(st-e 主 + ali 入口重定向)"小节、st-e 部署两条命令(`git push st main` + `ssh st-e-ecs-2 .../deploy.sh`)、ali 重定向容器起停与切回反代的说明。
- `.env.example`:登记 `AGENT_CLOUD_WEB_PORT`(默认 8080)、`AGENT_CLOUD_SANDBOX_MEM_LIMIT`(默认 256m)。

---

## 5. Part B — 迁移 runbook(ops;Part A 已在 main 且已推两台后执行)

记号:`ssh ali-ecs`(源)、`ssh st-e-ecs-2`(目标)、本机做两台之间的中转桥(两台服务器之间不互通)。

### B-pre. 代码就位(Part A 已合并到 main)
```bash
# 本机:把含 Part A 的 main 推到两台裸仓库
git push ali main                                        # ali 取到 deploy/ali-entry/(B4-5 用)
git remote add st st-e-ecs-2:/opt/agent-cloud/repo.git || git remote set-url st st-e-ecs-2:/opt/agent-cloud/repo.git
```
> 此处 `git push st` 在 B0 建好 st-e 裸仓库后才能成功,故放 B0 内。

### B0. st-e 准备(零停机,ali 仍正常服务)
```bash
# compose 插件
ssh st-e-ecs-2 'sudo apt-get update -qq && sudo apt-get install -y docker-compose-plugin && docker compose version'
# 目录归 sophgo(免 sudo 跑 deploy/git)
ssh st-e-ecs-2 'sudo mkdir -p /opt/agent-cloud/data/workspaces && sudo chown -R sophgo:sophgo /opt/agent-cloud'
# 裸仓库 + 工作树(镜像 ali 模式)
ssh st-e-ecs-2 'git init --bare /opt/agent-cloud/repo.git'
git push st main                                         # 本机 → st-e 裸仓库
ssh st-e-ecs-2 'git clone /opt/agent-cloud/repo.git /opt/agent-cloud/app'
```

### B1. .env 直传(**流式、绝不打印进日志/上下文**)
```bash
ssh ali-ecs 'cat /opt/agent-cloud/app/.env' | ssh st-e-ecs-2 'cat > /opt/agent-cloud/app/.env'
ssh st-e-ecs-2 'cd /opt/agent-cloud/app
  grep -q "^AGENT_CLOUD_WEB_PORT="          .env || echo "AGENT_CLOUD_WEB_PORT=18080"        >> .env
  grep -q "^AGENT_CLOUD_SANDBOX_MEM_LIMIT=" .env || echo "AGENT_CLOUD_SANDBOX_MEM_LIMIT=2g"  >> .env
  chmod 600 .env'
```
> `cat | ssh cat>` 的字节只在 ali→本机管道→st-e 之间流动,Bash 工具仅捕获最终命令 stdout(空),密钥不进上下文。

### B2. 镜像就位 + 只起 db(零停机)
**搬 ali 已构建好的镜像**(而非在 st-e 重建):规避 st-e 访问 npm/pypi/apt 的不确定性,且让 st-e 与现行 prod **逐位一致**。compose.yml 同时有 `build:` 与 `image:`,镜像已存在时 `up`(不带 `--build`)直接用、不重建。
```bash
ssh st-e-ecs-2 'cd /opt/agent-cloud/app && git pull --ff-only'   # 取到新 compose.yml(18080 端口插值)
# 把 ali 现有镜像 save→load 到 st-e(app 镜像 backend/worker 共用,一份即可)
for img in agent-cloud-app:latest agent-cloud-web:latest agent-cloud-sandbox:latest; do
  ssh ali-ecs "docker save $img" | ssh st-e-ecs-2 "docker load"
done
# 基础镜像:st-e 拉 postgres(Docker Hub 可达性以此步实际验证;ali 的 nginx:alpine 由 B4-5 compose up 自动拉)
ssh st-e-ecs-2 'docker pull postgres:16-alpine'
# 只起 db(用 .env 的 DB 密码全新初始化;backend 暂不起,避免 alembic 在空库建表与 dump 冲突)
ssh st-e-ecs-2 'cd /opt/agent-cloud/app && docker compose --env-file .env -f deploy/compose.yml up -d db'
ssh st-e-ecs-2 'cd /opt/agent-cloud/app && docker compose --env-file .env -f deploy/compose.yml ps'  # 等 db healthy
# objstore 卷此刻尚未被任何已起服务引用,显式建好,供 B3 灌入
ssh st-e-ecs-2 'docker volume create agent-cloud_objstore'
```
> 备选:若想用 main 最新代码而非 ali 镜像,且 st-e 能连包仓库,可改为 `docker build` + `compose build`(32 核很快)。本 runbook 默认搬镜像以求稳。

### B3. 预同步大块数据(零停机;切换时再补增量)
```bash
# workspaces:经本机 /tmp 暂存做两段 rsync(后续切换增量极快)。宿主文件归属无所谓
# (backend/sandbox 容器均以 root 访问,root 越权读写;不加 sudo/-o/-g)。
mkdir -p /tmp/ac-migrate/workspaces
rsync -a --delete -e ssh ali-ecs:/opt/agent-cloud/data/workspaces/ /tmp/ac-migrate/workspaces/
rsync -a          -e ssh /tmp/ac-migrate/workspaces/ st-e-ecs-2:/opt/agent-cloud/data/workspaces/
```

### B4. 切换(**停机窗口开始**;此步前向用户确认)
```bash
# 1) ali:停写入端(db 保留供 dump)
ssh ali-ecs 'cd /opt/agent-cloud/app && docker compose --env-file .env -f deploy/compose.yml stop backend worker web'

# 2) pgdata 逻辑迁移:ali pg_dump → st-e psql(两边都 postgres:16,容器内 trust 本地 socket,无需密码)
ssh ali-ecs 'docker exec agent-cloud-db-1 pg_dump -U postgres -d agent_cloud --clean --if-exists' \
  | ssh st-e-ecs-2 'docker exec -i agent-cloud-db-1 psql -U postgres -d agent_cloud -v ON_ERROR_STOP=1'

# 3) 末次增量:workspaces(rsync 仅传变化)+ objstore(424K 直接整包)
rsync -a --delete -e ssh ali-ecs:/opt/agent-cloud/data/workspaces/ /tmp/ac-migrate/workspaces/
rsync -a          -e ssh /tmp/ac-migrate/workspaces/ st-e-ecs-2:/opt/agent-cloud/data/workspaces/
ssh ali-ecs 'docker run --rm -v agent-cloud_objstore:/v:ro -w /v alpine tar -cf - .' \
  | ssh st-e-ecs-2 'docker run --rm -i -v agent-cloud_objstore:/v -w /v alpine tar -xf -'

# 4) st-e:起全栈(backend 启动跑 alembic = no-op,挂上迁移好的数据)
ssh st-e-ecs-2 'cd /opt/agent-cloud/app && docker compose --env-file .env -f deploy/compose.yml up -d'
ssh st-e-ecs-2 'cd /opt/agent-cloud/app && docker compose --env-file .env -f deploy/compose.yml ps'
ssh st-e-ecs-2 'curl -fsS localhost:18080/api/health'        # web(18080)→ backend

# 5) ali:停整个应用栈(保留容器+卷作回滚),起 302 重定向入口
ssh ali-ecs 'cd /opt/agent-cloud/app && docker compose --env-file .env -f deploy/compose.yml stop'
ssh ali-ecs 'cd /opt/agent-cloud/app && git pull --ff-only'   # 取到 deploy/ali-entry/
ssh ali-ecs 'cd /opt/agent-cloud/app/deploy/ali-entry && docker compose up -d'
```

### B5. 验证(停机窗口结束判据)
```bash
curl -fsS http://106.75.235.242:18080/api/health    # 直连主入口(用户已开网关端口)
curl -sSI http://47.94.140.245:8080/foo/bar | grep -i '^location'
#   期望: Location: http://106.75.235.242:18080/foo/bar(302 + 路径保留)
curl -fsSL http://47.94.140.245:8080/api/health     # -L 跟随重定向,端到端通
```
浏览器开 `http://47.94.140.245:8080/`:自动跳到 `106.75.235.242:18080` → **重新登录**(预期内,localStorage 按源)→ 列会话(数据已迁)→ 发一条消息走完整回合(st-e→worker→沙箱,验证 SSE 流式)→ 开一次终端(验证 WS)→ 传/下载一个文件(验证大带宽直连)。

### B6. 回滚(任一验证失败)
```bash
ssh ali-ecs 'cd /opt/agent-cloud/app/deploy/ali-entry && docker compose down'    # 撤重定向,放回 8080
ssh ali-ecs 'cd /opt/agent-cloud/app && docker compose --env-file .env -f deploy/compose.yml start'  # 原栈复活
```
ali 数据自始至终未删 → ~1 分钟回到迁移前。st-e 保持现状待排查。(302 非 301,浏览器不持久缓存,回滚后老 URL 行为立即恢复。)

### B7. 善后(稳定运行数日后)
- 删本机暂存 `/tmp/ac-migrate`。
- 确认稳定后再考虑清理 ali 应用栈(保留重定向容器);ali 数据卷在确信无需回滚前**不删**。
- 今后部署:`git push st main` + `ssh st-e-ecs-2 '/opt/agent-cloud/app/deploy/deploy.sh'`;ali 只跑重定向。
- 通知老用户新主入口 `http://106.75.235.242:18080/`(访问老地址也会自动跳过去)。

---

## 6. 风险与对策

| 风险 | 对策 |
|---|---|
| `.env` 不一致致旧密文/会话失效 | 逐字直传,仅追加两个端口/内存变量;DB 密码随之一致 |
| db 在 backend 起 alembic 后再灌 dump → 冲突 | B2 只起 db;dump 灌入后(B4-4)才起 backend,alembic 变 no-op |
| ali 带宽瓶颈(实测 3.5 Mbps vs st-e 168 Mbps) | 入口改 302 重定向,流量不过境 ali;已与用户确认接受地址栏变化 + 一次性重登 |
| 老用户被新 IP 地址栏吓到 / 不知要重登 | B7 通知用户;老入口永久有效,自动跳转 |
| 明文 HTTP 公网暴露(st-e:18080 直连) | 用户已决定暂不限制/不加密;与现有 user→ali 明文姿态一致;后续可加 |
| st-e 构建网络不确定(npm/pypi 可能被掐) | 不在 st-e 重建,直接 `docker save\|load` 搬 ali 现有镜像;与 prod 逐位一致 |
| st-e 18080 网关未放通 | B5 直连 curl 验证;未通则联系用户开通后再继续 |
| 密钥进日志 | `.env` 流式直传不打印;dump 走容器内 socket 无密码;不 echo 任何 secret |
| 误删数据 | 全程不 `down -v`;ali 卷保留;st-e 灌库用 `--clean --if-exists` 幂等可重跑 |

## 7. 待确认:无(三项决策已定;Phase 1 切换前再口头确认一次)
