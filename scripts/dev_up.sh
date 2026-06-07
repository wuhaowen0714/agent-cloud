#!/usr/bin/env bash
# 一键起全栈开发环境:Postgres(docker) + worker + backend(uvicorn) + frontend(vite)。
# 前置:仓库根 .env 里有 AGENT_CLOUD_WORKER_OPENAI_API_KEY / _BASE_URL;前端已 npm install;Docker 在跑。
# Ctrl-C 退出时清理后台进程 + Postgres 容器。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PG_NAME="agent-cloud-pg"
PG_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/agent_cloud"

# 载入仓库根 .env 并 export:worker 在 services/worker 下启动,其 pydantic env_file=".env"
# 只会找 services/worker/.env(不是根 .env),故必须在这里把根 .env 的凭据 export 给所有子进程。
# 环境变量优先级高于 pydantic 的 env_file。
if [[ -f "$ROOT/.env" ]]; then
  set -a; source "$ROOT/.env"; set +a
else
  echo "⚠ 未找到 $ROOT/.env —— worker 将缺少 OpenAI 凭据,回合会失败。请先按 .env.example 建 .env。"
fi

echo "[1/5] Postgres…"
if ! docker ps --format '{{.Names}}' | grep -q "^${PG_NAME}$"; then
  docker run -d --rm --name "$PG_NAME" -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=agent_cloud \
    -p 5432:5432 postgres:16 >/dev/null
fi
until docker exec "$PG_NAME" pg_isready -U postgres >/dev/null 2>&1; do sleep 0.5; done

echo "[2/5] migrate…"
( cd "$ROOT/services/backend" && AGENT_CLOUD_DATABASE_URL="$PG_URL" uv run alembic upgrade head )

pids=()
cleanup() {
  echo; echo "stopping…"
  for p in "${pids[@]:-}"; do [[ -n "$p" ]] && kill "$p" 2>/dev/null || true; done
  docker stop "$PG_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "[3/5] worker…"
( cd "$ROOT/services/worker" && uv run python -m agent_cloud_worker ) & pids+=($!)

echo "[4/5] backend (uvicorn :8000)…"
( cd "$ROOT/services/backend" && AGENT_CLOUD_DATABASE_URL="$PG_URL" AGENT_CLOUD_WORKER_ENDPOINT="localhost:50052" \
  AGENT_CLOUD_SANDBOX_BASE_ROOT="/tmp/agent-cloud-sandboxes" AGENT_CLOUD_OBJECT_STORE_ROOT="/tmp/agent-cloud-objstore" \
  uv run uvicorn agent_cloud_backend.main:app --port 8000 ) & pids+=($!)

echo "[5/5] frontend (vite :5173)…"
( cd "$ROOT/frontend" && npm run dev ) & pids+=($!)

echo "—— 打开 http://localhost:5173 —— (Ctrl-C 停止全部)"
wait
