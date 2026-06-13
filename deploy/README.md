# 部署(双机:st-e 主站 + ali 入口跳转 / docker compose)

```
老用户 ──> http://47.94.140.245:8080 (ali-ecs:仅一个 nginx,302 → 主站)
主站   ──> http://106.75.235.242:18080 (st-e-ecs-2:全应用栈 + 全部数据)
```

- **st-e-ecs-2**(`ssh st-e-ecs-2`,32核/62G):跑 db/backend/worker/web + 按需沙箱;**所有部署都在这台**。网关只放通 18080 → `.env` 设 `AGENT_CLOUD_WEB_PORT=18080`;大内存 → `AGENT_CLOUD_SANDBOX_MEM_LIMIT=2g`。
- **ali-ecs**(`ssh ali-ecs`,1.6G 小机):只跑 `deploy/ali-entry/` 的重定向容器,保住老入口。为什么不反代:ali 出向实测仅 ~3.5Mbps(st-e ~168Mbps),反代会封顶一切;重定向后流量直连 st-e。想临时切回反代:见 `deploy/ali-entry/nginx.conf` 内注释。
- 迁移过程与回滚预案留档:`docs/superpowers/specs/2026-06-13-migrate-to-st-e-ecs-2-design.md`。

## 布局(st-e,与迁移前的 ali 相同)

```
/opt/agent-cloud/
├── repo.git/  # 裸仓库(本机 push 的目标)
├── app/       # 工作树 clone(origin=本地裸仓库,git pull 即更新)
└── data/
    └── workspaces/   # 用户工作区(宿主目录,DooD 沙箱与 backend 同路径挂载)
```

数据持久化:Postgres 在 named volume `agent-cloud_pgdata`、技能对象库在 `agent-cloud_objstore`、工作区在宿主目录——**重新部署(build + up -d)全都不动**。⚠️ 永远不要对该 compose 项目执行 `down -v`。

## 代码如何到服务器(重要)

服务器对 GitHub 的可达性不可靠,代码经**服务器上的裸仓库**走 ssh 推送:

```
本机 git push st …  →  st-e-ecs-2:/opt/agent-cloud/repo.git(bare)  →  /opt/agent-cloud/app(clone)
```

本机一次性配置:`git remote add st st-e-ecs-2:/opt/agent-cloud/repo.git`(ali 同理:`git remote add ali ali-ecs:/opt/agent-cloud/repo.git`,现仅用于更新 ali-entry 配置)。

## 重新部署(改代码后,两条命令)

```bash
git push st main                                          # 本机:推最新代码到 st-e 裸仓库
ssh st-e-ecs-2 '/opt/agent-cloud/app/deploy/deploy.sh'    # 服务器:pull → build → up -d
```

(数据库迁移由 backend 容器启动时自动执行 `alembic upgrade head`;pgdata/objstore 卷与工作区目录不受影响。)

## ali 入口运维

```bash
ssh ali-ecs 'cd /opt/agent-cloud/app/deploy/ali-entry && docker compose up -d'   # 起重定向
ssh ali-ecs 'cd /opt/agent-cloud/app/deploy/ali-entry && docker compose down'    # 停(8080 让位)
# 改向/切反代:编辑 deploy/ali-entry/nginx.conf → git push ali main → ssh ali-ecs 'cd /opt/agent-cloud/app && git pull --ff-only' → 上面 restart
```

ali 上的旧应用栈容器与数据卷(pgdata/objstore/workspaces)**保留作回滚**,确信稳定前不清理;回滚 = down 重定向 + `docker compose start` 旧栈(见迁移 spec §B6)。

## 首次部署一台新机(留档)

```bash
# 本机
git remote add <name> <host>:/opt/agent-cloud/repo.git && git push <name> main
# 服务器
sudo mkdir -p /opt/agent-cloud/data/workspaces && sudo chown -R $USER /opt/agent-cloud
git init --bare /opt/agent-cloud/repo.git        # 然后本机 push
git clone /opt/agent-cloud/repo.git /opt/agent-cloud/app
cd /opt/agent-cloud/app
cp .env.example .env   # 填 LLM 凭据,并追加:
# AGENT_CLOUD_AUTH_SECRET=$(openssl rand -hex 48)
# AGENT_CLOUD_CREDENTIAL_KEY=$(python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())")
# AGENT_CLOUD_DB_PASSWORD=$(openssl rand -base64 24)   # 缺失则 deploy 直接 fail-loud
# 视机器追加 AGENT_CLOUD_WEB_PORT / AGENT_CLOUD_SANDBOX_MEM_LIMIT
bash deploy/deploy.sh
```

小内存机(如 ali 1.6G)建议配 2G swap(`/swapfile` + fstab)并保持沙箱 256m 上限。

## 组件与网络

- compose 项目名 `agent-cloud`,网络固定命名 `agent-cloud-net`(DockerProvisioner 按此名把沙箱容器接入,worker 经容器名直连沙箱 50051)。
- `db`(postgres:16-alpine,不发布端口)/ `backend`(:8000 仅内网;挂 docker.sock 做 DooD)/ `worker`(:50052 仅内网,持 LLM 凭据)/ `web`(nginx,**`${AGENT_CLOUD_WEB_PORT:-8080}` → 80**,静态 SPA + `/api` 反代,SSE 不缓冲)。
- 与宿主上已有的其它服务网络/卷/端口零交集(st-e 宿主另有他人 nginx 占 80/443/8359/8459,勿动)。

## 运维速查(st-e)

```bash
cd /opt/agent-cloud/app
docker compose --env-file .env -f deploy/compose.yml ps        # 状态
docker compose --env-file .env -f deploy/compose.yml logs -f backend   # 看日志(worker/web/db 同理)
docker ps -f label=managed-by=agent-cloud                      # 在跑的沙箱容器(空闲 30min 自动回收)
docker compose --env-file .env -f deploy/compose.yml restart backend   # 单服务重启
curl -fsS localhost:18080/api/health                           # 健康检查
```
