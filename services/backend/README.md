# Agent Cloud Backend

FastAPI 后端:**唯一**访问 Postgres 的服务。负责鉴权与多租户、会话/回合编排(SSE 流式、会话锁、压缩、自动重试)、文件与技能、BYO-Key 凭据、智能体记忆,并经 provisioner 管理沙箱生命周期。

架构、特性与配置见仓库根 [README](../../README.md);设计文档索引见 [docs/README.md](../../docs/README.md)。API 文档:服务起来后访问 `http://localhost:8000/docs`(FastAPI 自带)。

## 开发

```bash
cd services/backend

# 测试(testcontainers 起临时 Postgres;本环境需禁用 Ryuk)
TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker"

# 数据库迁移(对运行中的库)
AGENT_CLOUD_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/agent_cloud \
  uv run alembic upgrade head

# 单独起服务(平时建议直接用仓库根的 bash scripts/dev_up.sh 一键起全栈)
uv run uvicorn agent_cloud_backend.main:app --reload
```

代码布局:`api/`(路由)· `repositories/`(数据访问)· `models/`(ORM)· `schemas/`(Pydantic)· `turn/`(回合编排:runner / 压缩 / 记忆提炼 / 重试)· `sandbox/`(provisioner)· `skills/` · `files/` · `auth/`。
