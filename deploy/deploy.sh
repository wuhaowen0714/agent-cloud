#!/usr/bin/env bash
# 服务器端一键(重新)部署:git pull → 构建沙箱镜像 + 应用镜像 → up -d。
# 数据安全:只 build/up,从不 down -v —— pgdata/objstore 卷与宿主工作区目录永不触碰。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "✗ 缺少 $ROOT/.env(LLM 凭据 + AUTH_SECRET + CREDENTIAL_KEY),先按 .env.example 配置" >&2
  exit 1
fi

echo "[1/4] git pull…"
git pull --ff-only

echo "[2/4] 构建沙箱镜像…"
docker build -f deploy/sandbox.Dockerfile -t agent-cloud-sandbox:latest .

echo "[3/4] 构建并启动应用…"
mkdir -p /opt/agent-cloud/data/workspaces
# --env-file 显式指向根 .env:否则 -f deploy/compose.yml 会把 compose 变量插值的
# project-dir 设为 deploy/(读 deploy/.env),与 env_file(../.env)分裂。统一到根 .env,
# 让 ${AGENT_CLOUD_DB_PASSWORD:?} 等插值与容器 env 同源。
COMPOSE=(docker compose --env-file "$ROOT/.env" -f deploy/compose.yml)
"${COMPOSE[@]}" build
"${COMPOSE[@]}" up -d

echo "[4/4] 清理悬空镜像…"
docker image prune -f >/dev/null

"${COMPOSE[@]}" ps
echo "✓ 部署完成:http://<公网IP>:8080(健康检查:curl -s localhost:8080/api/health)"
