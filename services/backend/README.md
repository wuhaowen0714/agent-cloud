# Agent Cloud Backend

## 开发

```bash
# 起本地 Postgres
docker run -d --name agent-cloud-pg -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=agent_cloud -p 5432:5432 postgres:16

cd services/backend
uv run alembic upgrade head            # 迁移
uv run uvicorn agent_cloud_backend.main:app --reload   # 起服务
uv run pytest -v                       # 测试(需 Docker:testcontainers)
```
