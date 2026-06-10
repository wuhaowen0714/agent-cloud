# 部署(阿里云单机 / docker compose)

目标机现状约束:8000 端口已被其它服务占用 → 本应用**只发布 8080**;机器内存小(1.6G)→ 沙箱内存上限压到 256m,建议配 2G swap。

## 布局

```
/opt/agent-cloud/
├── app/    # 本仓库 clone(git pull 即更新)
└── data/
    └── workspaces/   # 用户工作区(宿主目录,DooD 沙箱与 backend 同路径挂载)
```

数据持久化:Postgres 在 named volume `agent-cloud_pgdata`、技能对象库在 `agent-cloud_objstore`、工作区在宿主目录——**重新部署(build + up -d)全都不动**。⚠️ 永远不要对该 compose 项目执行 `down -v`。

## 首次部署

```bash
ssh ali-ecs
git clone https://github.com/wuhaowen0714/agent-cloud.git /opt/agent-cloud/app
cd /opt/agent-cloud/app
cp .env.example .env   # 填 LLM 凭据,并追加:
# AGENT_CLOUD_AUTH_SECRET=$(openssl rand -base64 48)
# AGENT_CLOUD_CREDENTIAL_KEY=$(openssl rand -base64 32)
bash deploy/deploy.sh
```

阿里云控制台安全组放行 **8080/tcp** 后,访问 `http://<公网IP>:8080`。

## 重新部署(改代码后)

```bash
ssh ali-ecs '/opt/agent-cloud/app/deploy/deploy.sh'
```

(= git pull → 构建沙箱/应用/前端镜像 → `compose up -d`;数据库迁移由 backend 容器启动时自动执行 `alembic upgrade head`。)

## 组件与网络

- compose 项目名 `agent-cloud`,网络固定命名 `agent-cloud-net`(DockerProvisioner 按此名把沙箱容器接入,worker 经容器名直连沙箱 50051)。
- `db`(postgres:16-alpine,不发布端口)/ `backend`(:8000 仅内网;挂 docker.sock 做 DooD)/ `worker`(:50052 仅内网,持 LLM 凭据)/ `web`(nginx,**8080 → 80**,静态 SPA + `/api` 反代,SSE 不缓冲)。
- 与宿主上已有的 compose 项目(其它业务)网络/卷/端口零交集。

## 运维速查

```bash
cd /opt/agent-cloud/app
docker compose -f deploy/compose.yml ps           # 状态
docker compose -f deploy/compose.yml logs -f backend   # 看日志(worker/web/db 同理)
docker ps -f label=managed-by=agent-cloud         # 在跑的沙箱容器(空闲 30min 自动回收)
docker compose -f deploy/compose.yml restart backend   # 单服务重启
```
